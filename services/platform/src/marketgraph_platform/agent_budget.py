"""Platform-owned reservations for metered agent model calls.

Reservations survive worker crashes and count against both ceilings until a
successful call is settled with provider-reported usage. Prices are configured
conservatively by the operator; they are estimates, not verified invoices.
"""

from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from marketgraph_platform.agent_repository import WorkConflict, locked_job

_QUANTUM = Decimal("0.000000001")
_BUDGET_LOCK = 837290184


def estimate(input_tokens, output_tokens, input_rate, output_rate):
    amount = (Decimal(input_tokens) * Decimal(str(input_rate)) +
              Decimal(output_tokens) * Decimal(str(output_rate))) / Decimal(1_000_000)
    return amount.quantize(_QUANTUM, rounding=ROUND_CEILING)


async def reserve(pool, job_id, lease, body, settings):
    if not settings.agent_model_id or not settings.agent_input_usd_per_million or not settings.agent_output_usd_per_million:
        raise WorkConflict("Agent model and conservative rates must be configured")
    if body.model != settings.agent_model_id:
        raise WorkConflict("Model does not match the configured agent budget")
    amount = estimate(body.input_tokens, body.output_tokens,
                      settings.agent_input_usd_per_million, settings.agent_output_usd_per_million)
    async with pool.acquire() as conn, conn.transaction():
        job, access = await locked_job(conn, job_id, lease)
        if job['state'] != 'running':
            raise WorkConflict('Only running jobs can reserve model usage')
        if not access.developer:
            raise WorkConflict('Agent pilot is restricted to developer jobs')
        await conn.execute('SELECT pg_advisory_xact_lock($1)', _BUDGET_LOCK)
        existing = await conn.fetchrow(
            'SELECT * FROM agent_model_reservations WHERE job_id=$1 AND request_key=$2',
            job_id, body.request_key)
        if existing:
            if (existing['model'], existing['input_tokens'], existing['output_tokens']) != (
                body.model, body.input_tokens, body.output_tokens
            ):
                raise WorkConflict('Reservation key was used with different limits')
            return dict(existing)
        count, job_total = await conn.fetchrow(
            'SELECT count(*),coalesce(sum(charged_usd),0) FROM agent_model_reservations WHERE job_id=$1', job_id)
        month = await conn.fetchval("SELECT date_trunc('month',now() AT TIME ZONE 'UTC')::date")
        month_total = await conn.fetchval(
            'SELECT coalesce(sum(charged_usd),0) FROM agent_model_reservations WHERE month=$1', month)
        if count >= 4:
            raise WorkConflict('Agent job model-call limit exhausted')
        if job_total + amount > Decimal(str(settings.agent_job_usd_cap)):
            raise WorkConflict('Agent job budget exhausted')
        if month_total + amount > Decimal(str(settings.agent_monthly_usd_cap)):
            raise WorkConflict('Agent monthly budget exhausted')
        row = await conn.fetchrow(
            'INSERT INTO agent_model_reservations(id,job_id,request_key,model,input_tokens,output_tokens,'
            'input_rate,output_rate,reserved_usd,charged_usd,month) '
            'VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$9,$10) RETURNING *',
            uuid4(), job_id, body.request_key, body.model, body.input_tokens, body.output_tokens,
            Decimal(str(settings.agent_input_usd_per_million)),
            Decimal(str(settings.agent_output_usd_per_million)), amount, month)
        return dict(row)


async def settle(pool, job_id, lease, reservation_id, body):
    async with pool.acquire() as conn, conn.transaction():
        job, _ = await locked_job(conn, job_id, lease)
        if job['state'] != 'running':
            raise WorkConflict('Only running jobs can settle model usage')
        await conn.execute('SELECT pg_advisory_xact_lock($1)', _BUDGET_LOCK)
        row = await conn.fetchrow(
            'SELECT * FROM agent_model_reservations WHERE id=$1 AND job_id=$2 FOR UPDATE',
            reservation_id, job_id)
        if not row:
            raise WorkConflict('Unknown model reservation')
        if body.input_tokens > row['input_tokens'] or body.output_tokens > row['output_tokens']:
            raise WorkConflict('Reported usage exceeds reserved token limits')
        if row['settled']:
            if (row['used_input_tokens'], row['used_output_tokens']) != (body.input_tokens, body.output_tokens):
                raise WorkConflict('Reservation already settled with different usage')
            return dict(row)
        charged = estimate(body.input_tokens, body.output_tokens, row['input_rate'], row['output_rate'])
        row = await conn.fetchrow(
            'UPDATE agent_model_reservations SET settled=true,charged_usd=$3,used_input_tokens=$4,'
            'used_output_tokens=$5 WHERE id=$1 AND job_id=$2 RETURNING *',
            reservation_id, job_id, charged, body.input_tokens, body.output_tokens)
        return dict(row)
