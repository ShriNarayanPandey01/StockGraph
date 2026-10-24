"""User-scoped work queues. External agents never receive owner credentials."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4


class WorkConflict(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ('input', 'result', 'evidence', 'tickers'):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result


async def create_job(pool, user_id, kind, payload, key, max_pending=20):
    digest = fingerprint({'kind': kind, 'input': payload})
    async with pool.acquire() as conn, conn.transaction():
        # Serialize admission per owner, not across all users. This ceiling is
        # operational queue backpressure and is unrelated to a subscription.
        await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE', user_id)
        existing = await conn.fetchrow('SELECT * FROM agent_jobs WHERE user_id=$1 AND request_key=$2', user_id, key)
        if existing:
            if existing['fingerprint'] != digest:
                raise WorkConflict('Idempotency key was used with a different request')
            return unpack(existing)
        count = await conn.fetchval("SELECT count(*) FROM agent_jobs WHERE user_id=$1 AND state IN ('pending','running')", user_id)
        if count >= max_pending:
            raise WorkConflict('Operational work queue is full; retry after pending work finishes')
        if payload.get('conversation_id'):
            if not await conn.fetchval('SELECT id FROM conversations WHERE id=$1 AND user_id=$2 FOR SHARE',UUID(payload['conversation_id']),user_id):
                raise WorkConflict('Conversation is not owned by this user')
            await conn.execute(
                "INSERT INTO research_messages(id,conversation_id,user_id,role,content) VALUES($1,$2,$3,'user',$4)",
                UUID(payload['user_message_id']),UUID(payload['conversation_id']),user_id,payload['question'],
            )
        row = await conn.fetchrow(
            'INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint) VALUES($1,$2,$3,$4::jsonb,$5,$6) RETURNING *',
            uuid4(), user_id, kind, json.dumps(payload, default=str), key, digest,
        )
        return unpack(row)


async def claim_job(pool, settings):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE agent_jobs SET state='failed',error='Agent lease expired; retry budget exhausted',finished_at=now() "
            "WHERE state='running' AND lease_until<now() AND attempts >= $1", settings.max_agent_attempts,
        )
        row = await conn.fetchrow(
            "SELECT id FROM agent_jobs WHERE (state='pending' OR (state='running' AND lease_until<now())) "
            'AND attempts<$1 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1', settings.max_agent_attempts,
        )
        if not row:
            return None
        result = await conn.fetchrow(
            "UPDATE agent_jobs SET state='running',attempts=attempts+1,lease_token=$2,"
            "lease_until=now()+make_interval(secs=>$3),error=NULL WHERE id=$1 RETURNING *",
            row['id'], uuid4(), settings.agent_lease_seconds,
        )
        return unpack(result)


async def leased_job(conn, job_id, lease_token, *, lock=False):
    row = await conn.fetchrow('SELECT * FROM agent_jobs WHERE id=$1' + (' FOR UPDATE' if lock else ''), job_id)
    if not row or row['lease_token'] != lease_token:
        raise WorkConflict('Job lease does not match')
    if row['state'] != 'completed' and (
        row['state'] != 'running' or row['lease_until'] <= datetime.now(UTC)
    ):
        raise WorkConflict('Job lease is inactive or expired')
    return unpack(row)


async def audit_access(conn, job_id, actor, action):
    await conn.execute('INSERT INTO agent_access_audit(job_id,actor,action) VALUES($1,$2,$3)', job_id, actor, action)


async def reserve_tool_call(pool, job_id, lease_token, actor):
    async with pool.acquire() as conn, conn.transaction():
        job = await leased_job(conn, job_id, lease_token, lock=True)
        if job['state'] != 'running':
            raise WorkConflict('Completed work cannot retrieve more context')
        calls = await conn.fetchval(
            "INSERT INTO agent_usage(user_id,job_id,metric,amount) VALUES($1,$2,'tool_calls',1) "
            "ON CONFLICT(job_id,metric) DO UPDATE SET amount=agent_usage.amount+1 "
            'WHERE agent_usage.amount<100 RETURNING amount', job['user_id'], job_id)
        if calls is None:
            raise WorkConflict('Operational tool budget exhausted')
        await audit_access(conn, job_id, actor, 'tool.read')
        return job


async def register_evidence(pool, job_id, lease_token, entries):
    """Only server-fetched sources can enter this ledger; agents cannot write it."""
    offered = []
    async with pool.acquire() as conn, conn.transaction():
        job = await leased_job(conn, job_id, lease_token, lock=True)
        if job['state'] != 'running':
            raise WorkConflict('Completed work cannot retrieve more context')
        for entry in entries:
            if entry['ticker'] not in job['input']['tickers']:
                raise WorkConflict('Evidence is outside the job scope')
            source = entry['source']
            quote = entry['quote_text'][:50000]
            if not quote.strip():
                continue
            locator = entry.get('locator') or ''
            material = fingerprint({'kind': entry['kind'], 'id': entry['id'], 'text': quote,
                                    'ticker': entry['ticker'], 'locator': locator})
            expires = entry.get('eligible_until') or datetime.now(UTC) + timedelta(hours=1)
            await conn.execute(
                'INSERT INTO job_evidence(job_id,kind,evidence_id,locator,ticker,source,quote_text,material_version,lease_token,eligible_until) '
                'VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10) ON CONFLICT(job_id,kind,evidence_id,locator) '
                'DO UPDATE SET source=EXCLUDED.source,quote_text=EXCLUDED.quote_text,material_version=EXCLUDED.material_version,'
                'lease_token=EXCLUDED.lease_token,eligible_until=EXCLUDED.eligible_until,fetched_at=now()',
                job_id, entry['kind'], entry['id'], locator, entry['ticker'], json.dumps(source, default=str),
                quote, material, lease_token, expires)
            offered.append({'kind': entry['kind'], 'id': entry['id'], 'locator': locator or None,
                            'quote_text': quote, 'material_version': material, 'ticker': entry['ticker']})
    return offered


async def validate_result_evidence(conn, job, lease_token, result):
    references = list(result.get('evidence', []))
    status = result.get('status', 'supported')
    if status not in ('supported', 'insufficient_evidence'):
        raise WorkConflict('Unknown research result status')
    if status == 'supported' and not references:
        raise WorkConflict('Supported answers require source citations')
    if status == 'insufficient_evidence' and result.get('alerts'):
        raise WorkConflict('Insufficient evidence cannot generate opportunity alerts')
    for alert in result.get('alerts', []):
        references.extend(alert['evidence'])
    available = {}
    for reference in references:
        key = (reference['kind'], reference['id'], reference.get('locator') or '')
        if key not in available:
            row = await conn.fetchrow(
                'SELECT * FROM job_evidence WHERE job_id=$1 AND kind=$2 AND evidence_id=$3 AND locator=$4 '
                'AND lease_token=$5 AND eligible_until>now()', job['id'], *key, lease_token)
            if row is None:
                raise WorkConflict('Citation was not supplied to this active job or is no longer eligible')
            available[key] = row
            if key[0] == 'professional':
                try:
                    version_id = UUID(key[1])
                except ValueError:
                    raise WorkConflict('Professional citation identity is invalid') from None
                active = await conn.fetchval(
                    'SELECT c.id FROM platform_contributions c JOIN platform_contribution_versions v ON v.id=c.published_version_id '
                    'JOIN platform_users u ON u.id=c.author_id WHERE v.id=$1 AND c.retracted_at IS NULL '
                    'AND v.expires_at>now() AND u.professional_verified=true FOR SHARE OF c,v,u', version_id)
                if not active:
                    raise WorkConflict('Professional citation expired, changed, or was withdrawn')
        quote = reference.get('quote', '').strip()
        if not quote or quote not in available[key]['quote_text']:
            raise WorkConflict('Citation quote must be an exact excerpt from the supplied source')
    for alert in result.get('alerts', []):
        if alert['ticker'] not in job['input']['tickers']:
            raise WorkConflict('Alert stock is outside the canonical job scope')
        matched = False
        for reference in alert['evidence']:
            row = available[(reference['kind'], reference['id'], reference.get('locator') or '')]
            if row['ticker'] != alert['ticker']:
                raise WorkConflict('Alert evidence is outside its stock scope')
            if alert['event_id'] == row['evidence_id'] and alert['material_version'] == row['material_version']:
                matched = True
        if not matched:
            raise WorkConflict('Alert identity must use a supplied evidence ID and material version')


async def fail_job(pool, job_id, lease_token, retryable, max_attempts, actor):
    async with pool.acquire() as conn, conn.transaction():
        job = await leased_job(conn, job_id, lease_token, lock=True)
        if job['state'] != 'running':
            raise WorkConflict('Only running jobs can fail')
        state = 'pending' if retryable and job['attempts'] < max_attempts else 'failed'
        await audit_access(conn, job_id, actor, 'job.retry' if state == 'pending' else 'job.failed')
        return unpack(await conn.fetchrow(
            "UPDATE agent_jobs SET state=$2,lease_token=NULL,lease_until=NULL,error='External agent reported failure',"
            "finished_at=CASE WHEN $2='failed' THEN now() ELSE NULL END WHERE id=$1 RETURNING *", job_id, state))


async def complete_job(pool, job_id, lease_token, result):
    digest = fingerprint(result)
    async with pool.acquire() as conn, conn.transaction():
        job = await leased_job(conn, job_id, lease_token, lock=True)
        if job['state'] == 'completed':
            if job['result_fingerprint'] != digest:
                raise WorkConflict('Completed job received a different result')
            return job
        await validate_result_evidence(conn, job, lease_token, result)
        for alert in result.get('alerts', []):
            # The same canonical event/material revision is one opportunity
            # across agent retries and delivery channels. Account scope is SQL.
            dedupe = fingerprint({key: alert[key] for key in ('ticker','event_id','material_version')})
            await conn.execute(
                'INSERT INTO opportunity_alerts(id,user_id,job_id,ticker,direction,summary,evidence,dedupe_key) '
                'VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8) ON CONFLICT(user_id,dedupe_key) DO NOTHING',
                uuid4(), job['user_id'], job_id, alert['ticker'], alert['direction'], alert['summary'],
                json.dumps(alert['evidence']), dedupe,
            )
        conversation = job['input'].get('conversation_id')
        if conversation:
            await conn.execute(
                "INSERT INTO research_messages(id,conversation_id,user_id,role,content,evidence) VALUES($1,$2,$3,'assistant',$4,$5::jsonb)",
                uuid4(), UUID(conversation), job['user_id'], result['answer'], json.dumps(result['evidence']),
            )
        for metric, amount in {'completed_jobs': 1, 'reported_tokens': result.get('reported_tokens',0)}.items():
            await conn.execute(
                'INSERT INTO agent_usage(user_id,job_id,metric,amount) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',
                job['user_id'], job_id, metric, amount,
            )
        await audit_access(conn, job_id, 'external-agent', 'job.completed')
        return unpack(await conn.fetchrow(
            "UPDATE agent_jobs SET state='completed',result=$2::jsonb,result_fingerprint=$3,finished_at=now() WHERE id=$1 RETURNING *",
            job_id, json.dumps(result), digest,
        ))


async def schedule_due_monitors(pool, settings):
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            'SELECT m.*,w.tickers FROM monitors m JOIN watchlists w ON w.id=m.watchlist_id '
            "WHERE m.active AND m.next_run_at<=now() AND (SELECT count(*) FROM agent_jobs j "
            "WHERE j.user_id=m.user_id AND j.state IN ('pending','running'))<$2 ORDER BY m.next_run_at "
            'FOR UPDATE OF m SKIP LOCKED LIMIT $1', settings.monitor_batch_size,
            settings.operational_max_pending_jobs_per_user,
        )
        queued = 0
        for row in rows:
            await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE',row['user_id'])
            count = await conn.fetchval("SELECT count(*) FROM agent_jobs WHERE user_id=$1 AND state IN ('pending','running')",row['user_id'])
            if count >= settings.operational_max_pending_jobs_per_user:
                continue
            tickers = json.loads(row['tickers']) if isinstance(row['tickers'],str) else row['tickers']
            payload = {'monitor_id':str(row['id']), 'question':row['question'], 'tickers':tickers, 'window':'LAST_6M'}
            key = f"monitor:{row['id']}:{row['next_run_at'].isoformat()}"
            await conn.execute(
                "INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint) VALUES($1,$2,'monitor',$3::jsonb,$4,$5) "
                'ON CONFLICT(user_id,request_key) DO NOTHING',uuid4(),row['user_id'],json.dumps(payload),key,fingerprint(payload),
            )
            await conn.execute('UPDATE monitors SET next_run_at=now()+make_interval(secs=>interval_seconds) WHERE id=$1',row['id'])
            queued += 1
        return queued
