"""Run the repeatable Phase 1 verification matrix without production writes.

Use --live for isolated SQL/Falkor tests, --e2e for real loopback HTTP across
three services, and --upstox for separately reported read-only provider checks.
Databases/Redis must already be running; the runner never replaces containers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx


async def provision_test_database():
    from upstox_service.config.settings import Settings

    dsn = Settings().timescale_dsn
    parsed = urlsplit(dsn)
    if parsed.hostname not in {'localhost','127.0.0.1'}:
        raise ValueError('Integration bootstrap requires a local PostgreSQL server')
    name = 'platform_test_phase1_e2e'
    conn = await asyncpg.connect(dsn,timeout=10)
    try:
        if not await conn.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',name):
            await conn.execute('CREATE DATABASE platform_test_phase1_e2e')
    finally:
        await conn.close()
    return urlunsplit(parsed._replace(path='/'+name))


async def health_checks():
    checks = {}
    async with httpx.AsyncClient(timeout=8) as client:
        for name,base in [('data','http://127.0.0.1:8001'),('graph','http://127.0.0.1:8000'),
                          ('platform','http://127.0.0.1:8002')]:
            try:
                result = await client.get(base+'/health')
                checks[name] = {'status':'passed' if result.status_code==200 else 'failed',
                                'http_status':result.status_code}
            except Exception as exc:
                checks[name] = {'status':'failed','error_type':type(exc).__name__}
    return checks


def run(args):
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    output = root/'.cache'/'integration'/stamp
    output.mkdir(parents=True,exist_ok=False)
    report = {'started_at':datetime.now(UTC).isoformat(), 'live':args.live or args.e2e,
              'e2e':args.e2e,'paid_model_calls':False,'orders_submitted':False,'checks':{}}
    env = os.environ.copy()
    # Dotenv credentials remain in each owning Settings object, never in logs.
    if args.live or args.e2e:
        env.update(RUN_GRAPH_LIVE_TESTS='1',RUN_DATA_SQL_TESTS='1',
                   PLATFORM_TEST_DATABASE_DSN=asyncio.run(provision_test_database()))
    if args.e2e:
        env.update(RUN_PHASE1_E2E='1',E2E_REDIS_URL=args.redis_url)
    report['checks']['service_health'] = asyncio.run(health_checks())
    command = [sys.executable,'-m','pytest','tests','services/upstox/tests','services/stockgraph/tests',
               'services/platform/tests','-q','-p','no:cacheprovider',
               '--basetemp',str(output/'pytest'), '--junitxml',str(output/'pytest.xml')]
    print('Running offline and selected isolated integration checks. No existing application records are reset.',flush=True)
    tested = subprocess.run(command,env=env,cwd=root)
    report['checks']['pytest'] = {'status':'passed' if tested.returncode==0 else 'failed',
                                'exit_code':tested.returncode,'junit':str((output/'pytest.xml').relative_to(root))}
    lint = subprocess.run([sys.executable,'-m','ruff','check','services','scripts','tests'],cwd=root)
    report['checks']['ruff'] = {'status':'passed' if lint.returncode==0 else 'failed'}
    if args.upstox:
        smoke = subprocess.run([sys.executable,'scripts/verify_upstox_live.py'],env=env,cwd=root,
                               capture_output=True,text=True)
        # The smoke script deliberately emits only named capability statuses.
        try:
            provider = json.loads(smoke.stdout)
        except ValueError:
            provider = {'status':'failed','error':'Provider report unavailable; no response payload logged'}
        report['checks']['upstox'] = {'exit_code':smoke.returncode,'capabilities':provider}
        print(json.dumps(provider,indent=2))
    report['finished_at'] = datetime.now(UTC).isoformat()
    report_path = output/'report.json'
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Verification report: '+str(report_path.relative_to(root)))
    failed = tested.returncode!=0 or lint.returncode!=0
    failed = failed or any(c['status']!='passed' for c in report['checks']['service_health'].values())
    if args.upstox:
        failed = failed or report['checks']['upstox']['exit_code']!=0
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--e2e',action='store_true')
    parser.add_argument('--upstox',action='store_true')
    parser.add_argument('--redis-url',default='redis://127.0.0.1:16380/0',
                        help='Dedicated disposable E2E Redis; never use production Redis')
    try:
        return run(parser.parse_args())
    except Exception as exc:
        print(f'Integration preflight failed ({type(exc).__name__}); no application data reset.',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
