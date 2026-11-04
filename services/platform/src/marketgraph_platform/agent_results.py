"""Validate v2 agent results using only server-registered evidence."""

import json
from datetime import UTC, datetime
from uuid import UUID

from marketgraph_platform.agent_repository import WorkConflict, fingerprint

_RELATIONS = {'DIRECTLY_IMPACTS', 'INDIRECTLY_IMPACTS', 'SHOCKS', 'ALTERS_MACRO',
              'IMPACTS_SECTOR', 'EXPOSED_TO', 'SENSITIVE_TO_MACRO', 'BELONGS_TO',
              'SUPPLIES_TO', 'COMPETES_WITH'}


def _object(value):
    return json.loads(value) if isinstance(value, str) else value


async def prepare_v2(conn, job, lease, result, min_confidence, allow_professional):
    refs = list(result.get('evidence', []))
    for claim in result.get('claims', []):
        refs.extend(claim['evidence'])
    opportunities = result.get('opportunities', [])
    for item in opportunities:
        refs.extend([item['catalyst'], *item['connections'], *item['corroboration'], *item['counter_evidence']])
    available = {}
    for ref in refs:
        key = (ref['kind'], ref['id'], ref.get('locator') or '', ref['ticker'])
        if ref['ticker'] not in job['input']['tickers']:
            raise WorkConflict('Evidence is outside the job stock scope')
        if key not in available:
            row = await conn.fetchrow(
                'SELECT * FROM job_evidence WHERE job_id=$1 AND kind=$2 AND evidence_id=$3 '
                'AND locator=$4 AND ticker=$5 AND lease_token=$6 AND eligible_until>now()',
                job['id'], *key, lease)
            if row is None:
                raise WorkConflict('Citation was not supplied to this active job or is no longer eligible')
            available[key] = dict(row)
            if ref['kind'] == 'professional':
                try:
                    version_id = UUID(ref['id'])
                except ValueError:
                    raise WorkConflict('Professional citation identity is invalid') from None
                if not await conn.fetchval(
                    'SELECT c.id FROM platform_contributions c JOIN platform_contribution_versions v ON v.id=c.published_version_id '
                    'JOIN platform_users u ON u.id=c.author_id WHERE v.id=$1 AND c.retracted_at IS NULL '
                    'AND v.expires_at>now() AND u.professional_verified=true FOR SHARE OF c,v,u', version_id):
                    raise WorkConflict('Professional citation expired, changed, or was withdrawn')
        row = available[key]
        if ref['material_version'] != row['material_version']:
            raise WorkConflict('Citation material version changed')
        quote = ref.get('quote', '').strip()
        if not quote or quote not in row['quote_text']:
            raise WorkConflict('Citation quote must be an exact excerpt from the supplied source')

    coverage = result.get('coverage')
    if job['kind'] in ('discovery', 'monitor'):
        if result['status'] == 'supported' and not opportunities:
            raise WorkConflict('A supported opportunity result must include an opportunity')
        snapshot = await conn.fetchrow('SELECT * FROM agent_candidate_snapshots WHERE job_id=$1', job['id'])
        if snapshot is None or coverage is None or coverage['as_of_ts'] != snapshot['as_of_ts']:
            raise WorkConflict('A valid candidate snapshot and coverage are required')
        items = _object(snapshot['items'])
        candidates = {(item['ticker'], item['event_id'], item['material_version']) for item in items}
        selected = coverage['evaluated_tickers']
        if len(set(selected)) != len(selected) or any(ticker not in job['input']['tickers'] for ticker in selected):
            raise WorkConflict('Coverage contains an invalid stock scope')
        if coverage['candidates_total'] != len(items):
            raise WorkConflict('Candidate coverage does not match the snapshot')
        candidate_keys = {fingerprint([item['ticker'], item['event_id'], item['material_version']]) for item in items}
        selected_keys = {fingerprint([item['ticker'], item['event_id'], item['material_version']])
                         for item in items if item['ticker'] in selected}
        previous_keys, previous_complete = set(), None
        if job['kind'] == 'monitor':
            previous = await conn.fetchrow(
                'SELECT e.outcome,j.required_plan FROM agent_monitor_evaluations e '
                'JOIN agent_jobs j ON j.id=e.job_id WHERE e.monitor_id=$1 '
                'ORDER BY e.evaluated_at DESC,e.id DESC LIMIT 1', UUID(job['input']['monitor_id']))
            if previous and (previous['required_plan'] != 'PRO' or allow_professional):
                old_coverage = (_object(previous['outcome']).get('coverage') or {})
                previous_keys = set(old_coverage.get('evaluated_candidates', [])) & candidate_keys
                previous_complete = old_coverage.get('last_complete_ts')
            expected = previous_keys if result['status'] == 'insufficient_evidence' else previous_keys | selected_keys
            if set(coverage['evaluated_candidates']) != expected:
                raise WorkConflict('Monitoring candidate progress is invalid')
        else:
            expected = selected_keys
        partial = bool(snapshot['truncated'] or len(expected) < len(candidate_keys) or
                       (job['kind'] == 'monitor' and result['status'] == 'insufficient_evidence'))
        if partial != coverage['partial']:
            raise WorkConflict('Candidate coverage is inaccurate')
        if job['kind'] == 'monitor':
            expected_complete = previous_complete if partial else coverage['as_of_ts']
            if coverage['last_complete_ts'] != expected_complete:
                raise WorkConflict('Monitoring completion checkpoint is invalid')
    elif opportunities:
        raise WorkConflict('Research chat cannot issue opportunity alerts')
    else:
        candidates, selected = set(), []
        if result['status'] == 'no_opportunity':
            raise WorkConflict('Research chat must return a cited answer or insufficient evidence')
        if result['status'] == 'supported':
            claims = result.get('claims', [])
            if not claims or result['answer'] != '\n\n'.join(claim['text'] for claim in claims):
                raise WorkConflict('Research answers must be composed of individually cited claims')

    alerts, seen_catalysts = [], set()
    for item in opportunities:
        ticker, catalyst = item['ticker'], item['catalyst']
        identity = (ticker, catalyst['id'])
        if identity in seen_catalysts:
            raise WorkConflict('A result cannot contain duplicate opportunities for the same catalyst')
        seen_catalysts.add(identity)
        if ticker not in selected or (ticker, catalyst['id'], catalyst['material_version']) not in candidates:
            raise WorkConflict('Opportunity catalyst was not in the candidate snapshot')
        root = available[('news', catalyst['id'], catalyst.get('locator') or '', ticker)]
        news = _object(root['source'])
        try:
            event_ts = int(news['event_ts'])
        except (KeyError, TypeError, ValueError):
            raise WorkConflict('Catalyst timestamp is unavailable') from None
        if not coverage['as_of_ts'] - 72 * 3600 <= event_ts <= coverage['as_of_ts'] or event_ts < int(datetime.now(UTC).timestamp()) - 72 * 3600:
            raise WorkConflict('Catalyst is outside the 72-hour window')
        edges = []
        for ref in item['connections']:
            edge = _object(available[('graph', ref['id'], ref.get('locator') or '', ticker)]['source'])
            confidence = edge.get('confidence')
            if edge.get('relation') not in _RELATIONS or not isinstance(confidence, (float, int)) or confidence < min_confidence:
                raise WorkConflict('Connection does not meet relationship confidence rules')
            source, target = edge.get('source'), edge.get('target')
            if not isinstance(source, str) or not isinstance(target, str):
                raise WorkConflict('Connection endpoints are unavailable')
            edges.append((source, edge['relation'], target))
        news_node, stock_node = f'NewsEvent:{catalyst["id"]}', f'Stock:{ticker}'
        direct = any(source == news_node and target == stock_node and relation in {'DIRECTLY_IMPACTS', 'INDIRECTLY_IMPACTS'}
                     for source, relation, target in edges)
        shocks = {target for source, relation, target in edges if source == news_node and relation in {'SHOCKS', 'ALTERS_MACRO', 'IMPACTS_SECTOR'}}
        exposures = {target for source, relation, target in edges if source == stock_node and relation in {'EXPOSED_TO', 'SENSITIVE_TO_MACRO', 'BELONGS_TO', 'SUPPLIES_TO', 'COMPETES_WITH'}}
        if not direct and not shocks.intersection(exposures):
            raise WorkConflict('Graph path does not connect the catalyst to its stock')
        item_refs = [catalyst, *item['connections'], *item['corroboration'], *item['counter_evidence']]
        versions = sorted({(ref['kind'], ref['id'], ref.get('locator') or '', ref['material_version']) for ref in item_refs})
        revision = fingerprint(versions)
        alerts.append({'ticker': ticker, 'event_id': catalyst['id'], 'material_version': catalyst['material_version'],
                       'direction': item['direction'], 'summary': item['thesis'], 'evidence': item_refs,
                       'opportunity_revision': revision, 'opportunity': item})
    if job['kind'] in ('discovery', 'monitor'):
        answer = (f'{len(opportunities)} qualifying opportunities found.' if opportunities else
                  'No qualifying opportunity found.' if result['status'] == 'no_opportunity' else
                  'Insufficient evidence to evaluate an opportunity.')
        result = {**result, 'answer': answer}
    elif result['status'] == 'insufficient_evidence':
        result = {**result, 'answer': 'Insufficient evidence to answer this question.',
                  'evidence': [], 'claims': []}
    return {**result, 'alerts': alerts if job['kind'] == 'monitor' else []}
