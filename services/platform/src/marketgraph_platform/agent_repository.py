"""User-scoped work queues. External agents never receive owner credentials."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from marketgraph_platform.repository import PlatformError


async def job_access(conn, job):
    # Lazy import avoids the repository/entitlements cycle at application startup.
    from marketgraph_platform.entitlements import load_job_access

    access = await load_job_access(conn, job)
    access.require_job(job)
    return access


async def locked_job(conn, job_id, lease_token):
    # Account locks always precede job locks, matching selection/plan mutations.
    owner = await conn.fetchrow('SELECT user_id FROM agent_jobs WHERE id=$1', job_id)
    if owner is None:
        raise WorkConflict('Job lease does not match')
    await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE', owner['user_id'])
    job = await leased_job(conn, job_id, lease_token, lock=True)
    return job, await job_access(conn, job)


class WorkConflict(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ('input', 'result', 'evidence', 'tickers', 'opportunity'):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result


async def create_job(pool, user_id, kind, payload, key, max_pending=20, actor_id=None):
    digest = fingerprint({'kind': kind, 'input': payload, 'actor_id': actor_id})
    async with pool.acquire() as conn, conn.transaction():
        # Serialize admission per owner, not across all users. This ceiling is
        # operational queue backpressure and is unrelated to a subscription.
        await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE', user_id)
        required_plan = 'PRO' if kind == 'discovery' or payload.get('scope') == 'market' or (
            actor_id is not None and actor_id != user_id) else 'FREE'
        admission = {'user_id': user_id, 'actor_id': actor_id, 'kind': kind,
                     'input': payload, 'required_plan': required_plan}
        access = await job_access(conn, admission)
        existing = await conn.fetchrow('SELECT * FROM agent_jobs WHERE user_id=$1 AND request_key=$2', user_id, key)
        if existing:
            if existing['fingerprint'] != digest:
                raise WorkConflict('Idempotency key was used with a different request')
            await job_access(conn, unpack(existing))
            return unpack(existing)
        count = await conn.fetchval("SELECT count(*) FROM agent_jobs WHERE user_id=$1 AND state IN ('pending','running')", user_id)
        if not access.developer and count >= max_pending:
            raise WorkConflict('Operational work queue is full; retry after pending work finishes')
        if payload.get('conversation_id'):
            if not await conn.fetchval('SELECT id FROM conversations WHERE id=$1 AND user_id=$2 FOR SHARE',UUID(payload['conversation_id']),user_id):
                raise WorkConflict('Conversation is not owned by this user')
            await conn.execute(
                "INSERT INTO research_messages(id,conversation_id,user_id,role,content,required_plan) VALUES($1,$2,$3,'user',$4,'FREE')",
                UUID(payload['user_message_id']),UUID(payload['conversation_id']),user_id,payload['question'],
            )
        row = await conn.fetchrow(
            'INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint,required_plan,actor_id) '
            'VALUES($1,$2,$3,$4::jsonb,$5,$6,$7,$8) RETURNING *',
            uuid4(), user_id, kind, json.dumps(payload, default=str), key, digest, required_plan, actor_id,
        )
        if access.developer:
            from marketgraph_platform.entitlements import audit_admin

            await audit_admin(conn, access.user.id, 'agent.job.created', user_id,
                              {'job_id': str(row['id']), 'kind': kind})
        return unpack(row)


async def claim_job(pool, settings, *, developer_only=False, contract_version=1):
    pilot_filter = (" AND EXISTS (SELECT 1 FROM platform_users u WHERE u.id=agent_jobs.user_id "
                    "AND u.is_developer AND NOT u.disabled)" if developer_only else "")
    candidates = await pool.fetch(
        "SELECT id,user_id FROM agent_jobs WHERE (state='pending' OR "
        "(state='running' AND lease_until<now()))" + pilot_filter + " ORDER BY created_at LIMIT 100")
    for candidate in candidates:
        async with pool.acquire() as conn, conn.transaction():
            await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE', candidate['user_id'])
            if developer_only and not await conn.fetchval(
                'SELECT is_developer AND NOT disabled FROM platform_users WHERE id=$1', candidate['user_id']
            ):
                continue
            row = await conn.fetchrow(
                "SELECT * FROM agent_jobs WHERE id=$1 AND (state='pending' OR "
                "(state='running' AND lease_until<now())) FOR UPDATE SKIP LOCKED", candidate['id'])
            if row is None:
                continue
            job = unpack(row)
            try:
                await job_access(conn, job)
            except PlatformError as exc:
                if exc.status != 403:
                    raise
                await conn.execute(
                    "UPDATE agent_jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,"
                    "finished_at=now(),error='Current access policy does not permit this job' WHERE id=$1", job['id'])
                continue
            if job['attempts'] >= settings.max_agent_attempts:
                await conn.execute(
                    "UPDATE agent_jobs SET state='failed',lease_token=NULL,lease_until=NULL,finished_at=now(),"
                    "error='Agent retry budget exhausted' WHERE id=$1", job['id'])
                continue
            return unpack(await conn.fetchrow(
                "UPDATE agent_jobs SET state='running',attempts=attempts+1,lease_token=$2,"
                "lease_until=now()+make_interval(secs=>$3),error=NULL,contract_version=$4 WHERE id=$1 RETURNING *",
                job['id'], uuid4(), settings.agent_lease_seconds, contract_version))
    return None


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
        job, access = await locked_job(conn, job_id, lease_token)
        if job['state'] != 'running':
            raise WorkConflict('Completed work cannot retrieve more context')
        ceiling = ('WHERE agent_usage.amount<20 ' if job.get('contract_version', 1) == 2 else
                   '' if access.developer else 'WHERE agent_usage.amount<100 ')
        calls = await conn.fetchval(
            "INSERT INTO agent_usage(user_id,job_id,metric,amount) VALUES($1,$2,'tool_calls',1) "
            "ON CONFLICT(job_id,metric) DO UPDATE SET amount=agent_usage.amount+1 "
            + ceiling + 'RETURNING amount', job['user_id'], job_id)
        if calls is None:
            raise WorkConflict('Operational tool budget exhausted')
        await audit_access(conn, job_id, actor, 'tool.read')
        return job


async def register_evidence(pool, job_id, lease_token, entries):
    """Only server-fetched sources can enter this ledger; agents cannot write it."""
    offered = []
    async with pool.acquire() as conn, conn.transaction():
        job, access = await locked_job(conn, job_id, lease_token)
        if job['state'] != 'running':
            raise WorkConflict('Completed work cannot retrieve more context')
        if any(entry['kind'] == 'professional' for entry in entries):
            access.require('professional_evidence')
            await conn.execute("UPDATE agent_jobs SET required_plan='PRO' WHERE id=$1", job_id)
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
                'VALUES($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10) ON CONFLICT(job_id,kind,evidence_id,locator,ticker) '
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


async def fail_job(pool, job_id, lease_token, retryable, max_attempts, actor, reason='failure'):
    async with pool.acquire() as conn, conn.transaction():
        job, _ = await locked_job(conn, job_id, lease_token)
        if job['state'] != 'running':
            raise WorkConflict('Only running jobs can fail')
        state = 'pending' if retryable and job['attempts'] < max_attempts else 'failed'
        await audit_access(conn, job_id, actor, 'job.retry' if state == 'pending' else 'job.failed')
        return unpack(await conn.fetchrow(
            "UPDATE agent_jobs SET state=$2,lease_token=NULL,lease_until=NULL,error=$3,"
            "finished_at=CASE WHEN $2='failed' THEN now() ELSE NULL END WHERE id=$1 RETURNING *", job_id, state,
            'budget_blocked' if reason == 'budget_blocked' else 'External agent reported failure'))


async def complete_job(pool, job_id, lease_token, result, settings=None):
    digest = fingerprint(result)
    async with pool.acquire() as conn, conn.transaction():
        job, access = await locked_job(conn, job_id, lease_token)
        if job['state'] == 'completed':
            if job['result_fingerprint'] != digest:
                raise WorkConflict('Completed job received a different result')
            return job
        v2 = result.get('contract_version') == 2
        if v2:
            if job.get('contract_version') != 2 or settings is None:
                raise WorkConflict('This job does not permit the v2 result contract')
            from marketgraph_platform.agent_results import prepare_v2
            result = await prepare_v2(conn, job, lease_token, result, settings.agent_graph_min_confidence,
                                      access.allows('professional_evidence'))
        else:
            await validate_result_evidence(conn, job, lease_token, result)
        limit = access.policy['monthly_alert_limit']
        used = await conn.fetchval(
            "SELECT count(*) FROM opportunity_alerts WHERE user_id=$1 AND created_at >= "
            "(date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata') "
            "AND created_at < ((date_trunc('month',now() AT TIME ZONE 'Asia/Kolkata') + interval '1 month') "
            "AT TIME ZONE 'Asia/Kolkata')", job['user_id'])
        remaining = None if access.developer or limit is None else max(0, limit - used)
        created_alerts, suppressed, seen_alerts = [], 0, set()
        for alert in result.get('alerts', []):
            # The same canonical event/material revision is one opportunity
            # across agent retries and delivery channels. Account scope is SQL.
            dedupe = fingerprint({key: alert[key] for key in
                                  (('ticker','event_id','opportunity_revision') if v2 else
                                   ('ticker','event_id','material_version'))})
            if dedupe in seen_alerts:
                continue
            seen_alerts.add(dedupe)
            duplicate = await conn.fetchval(
                'SELECT EXISTS(SELECT 1 FROM opportunity_alerts WHERE user_id=$1 AND dedupe_key=$2)',
                job['user_id'], dedupe)
            if duplicate:
                continue
            if v2:
                previous = await conn.fetchrow(
                    'SELECT opportunity_revision FROM opportunity_alerts WHERE user_id=$1 AND ticker=$2 '
                    'AND catalyst_event_id=$3 ORDER BY created_at DESC,id DESC LIMIT 1',
                    job['user_id'], alert['ticker'], alert['event_id'])
                if previous and (previous['opportunity_revision'] == alert['opportunity_revision']
                                 or not alert['opportunity']['material_change']):
                    continue
                if not previous:
                    legacy = fingerprint({key: alert[key] for key in ('ticker','event_id','material_version')})
                    if await conn.fetchval(
                        'SELECT EXISTS(SELECT 1 FROM opportunity_alerts WHERE user_id=$1 AND dedupe_key=$2)',
                        job['user_id'], legacy):
                        continue
            if not access.allows('opportunity_alerts') or remaining == 0:
                suppressed += 1
                continue
            if v2:
                inserted = await conn.fetchval(
                    'INSERT INTO opportunity_alerts(id,user_id,job_id,ticker,direction,summary,evidence,dedupe_key,required_plan,'
                    'opportunity,catalyst_event_id,opportunity_revision) '
                    'VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11,$12) '
                    'ON CONFLICT(user_id,dedupe_key) DO NOTHING RETURNING id',
                    uuid4(), job['user_id'], job_id, alert['ticker'], alert['direction'], alert['summary'],
                    json.dumps(alert['evidence']), dedupe, job['required_plan'], json.dumps(alert['opportunity']),
                    alert['event_id'], alert['opportunity_revision'])
            else:
                inserted = await conn.fetchval(
                    'INSERT INTO opportunity_alerts(id,user_id,job_id,ticker,direction,summary,evidence,dedupe_key,required_plan) '
                    'VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9) ON CONFLICT(user_id,dedupe_key) DO NOTHING RETURNING id',
                    uuid4(), job['user_id'], job_id, alert['ticker'], alert['direction'], alert['summary'],
                    json.dumps(alert['evidence']), dedupe, job['required_plan'],
                )
            if inserted is not None:
                created_alerts.append(alert)
                if remaining is not None:
                    remaining -= 1
        stored_result = {**result, 'alerts': created_alerts, 'alerts_created': len(created_alerts),
                         'alerts_suppressed': suppressed}
        if v2 and job['kind'] == 'monitor':
            monitor_id = UUID(job['input']['monitor_id'])
            monitor = await conn.fetchval('SELECT id FROM monitors WHERE id=$1 AND user_id=$2 AND active FOR SHARE',
                                          monitor_id, job['user_id'])
            if not monitor:
                raise WorkConflict('Monitor is no longer active')
            await conn.execute(
                'INSERT INTO agent_monitor_evaluations(id,monitor_id,job_id,outcome) VALUES($1,$2,$3,$4::jsonb)',
                uuid4(), monitor_id, job_id, json.dumps(stored_result))
        conversation = job['input'].get('conversation_id')
        if conversation:
            await conn.execute(
                "INSERT INTO research_messages(id,conversation_id,user_id,role,content,evidence,required_plan) "
                "VALUES($1,$2,$3,'assistant',$4,$5::jsonb,$6)",
                uuid4(), UUID(conversation), job['user_id'], result['answer'], json.dumps(result['evidence']), job['required_plan'],
            )
        for metric, amount in {'completed_jobs': 1, 'reported_tokens': result.get('reported_tokens',0)}.items():
            await conn.execute(
                'INSERT INTO agent_usage(user_id,job_id,metric,amount) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',
                job['user_id'], job_id, metric, amount,
            )
        await audit_access(conn, job_id, 'external-agent', 'job.completed')
        return unpack(await conn.fetchrow(
            "UPDATE agent_jobs SET state='completed',result=$2::jsonb,result_fingerprint=$3,finished_at=now() WHERE id=$1 RETURNING *",
            job_id, json.dumps(stored_result), digest,
        ))


async def schedule_due_monitors(pool, settings):
    candidates = await pool.fetch(
        'SELECT id,user_id FROM monitors WHERE active AND next_run_at<=now() ORDER BY next_run_at LIMIT $1',
        settings.monitor_batch_size)
    queued = 0
    for candidate in candidates:
        async with pool.acquire() as conn, conn.transaction():
            await conn.fetchval('SELECT id FROM platform_users WHERE id=$1 FOR UPDATE', candidate['user_id'])
            row = await conn.fetchrow(
                'SELECT m.*,w.tickers FROM monitors m LEFT JOIN watchlists w ON w.id=m.watchlist_id '
                'WHERE m.id=$1 AND m.active AND m.next_run_at<=now() FOR UPDATE OF m SKIP LOCKED', candidate['id'])
            if row is None:
                continue
            scope = row['scope']
            tickers = [] if scope == 'market' else (
                json.loads(row['tickers']) if isinstance(row['tickers'], str) else list(row['tickers']))
            actor_id = row.get('actor_id')
            required_plan = 'PRO' if scope == 'market' or (actor_id and actor_id != row['user_id']) else 'FREE'
            payload = {'monitor_id': str(row['id']), 'question': row['question'], 'tickers': tickers,
                       'window': 'LAST_6M', 'scope': scope}
            synthetic_job = {'user_id': row['user_id'], 'actor_id': actor_id, 'kind': 'monitor',
                             'input': payload, 'required_plan': required_plan}
            try:
                from marketgraph_platform.entitlements import load_job_access

                access = await load_job_access(conn, synthetic_job)
                if not access.developer and not access.pro:
                    if not access.user.active_selection_initialized:
                        raise PlatformError(403, 'Select active stocks to resume')
                    payload['tickers'] = sorted(set(tickers) & set(access.tickers))
                    if not payload['tickers']:
                        raise PlatformError(403, 'No active stocks are eligible for this monitor')
                access.require_job(synthetic_job)
            except PlatformError as exc:
                if exc.status != 403:
                    raise
                await conn.execute(
                    "UPDATE monitors SET pause_reason='Current access or stock selection does not permit monitoring',"
                    "next_run_at=now()+make_interval(secs=>interval_seconds) WHERE id=$1", row['id'])
                continue
            count = await conn.fetchval(
                "SELECT count(*) FROM agent_jobs WHERE user_id=$1 AND state IN ('pending','running')", row['user_id'])
            if not access.developer and count >= settings.operational_max_pending_jobs_per_user:
                continue
            key = f"monitor:{row['id']}:{row['next_run_at'].isoformat()}"
            digest = fingerprint({'kind': 'monitor', 'input': payload, 'actor_id': actor_id})
            inserted = await conn.fetchval(
                "INSERT INTO agent_jobs(id,user_id,kind,input,request_key,fingerprint,required_plan,actor_id) "
                "VALUES($1,$2,'monitor',$3::jsonb,$4,$5,$6,$7) ON CONFLICT(user_id,request_key) DO NOTHING RETURNING id",
                uuid4(), row['user_id'], json.dumps(payload), key, digest, required_plan, actor_id)
            await conn.execute(
                'UPDATE monitors SET pause_reason=NULL,next_run_at=now()+make_interval(secs=>interval_seconds) WHERE id=$1', row['id'])
            queued += inserted is not None
    return queued
