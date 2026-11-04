"""Opt-in worker: lease supervision and bounded LangGraph execution."""

import asyncio
import logging
import os
import signal
from contextlib import suppress
from uuid import uuid4

from marketgraph_agents.model import BudgetBlocked, ModelFailure, ReservedModel, route
from marketgraph_agents.registry import AGENTS
from marketgraph_agents.settings import Settings
from marketgraph_agents.transport import HttpPlatformClient, PlatformCallError

logger = logging.getLogger(__name__)


async def _advertise(client, worker_id, stop):
    while not stop.is_set():
        try:
            await client.worker_heartbeat(worker_id, True)
        except PlatformCallError:
            logger.warning('Agent worker heartbeat failed')
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except TimeoutError:
            pass
    with suppress(PlatformCallError):
        await client.worker_heartbeat(worker_id, False)


async def _supervise_lease(client, job_id, lease, interval):
    while True:
        await asyncio.sleep(interval)
        await client.heartbeat(job_id, lease)


async def _safe_fail(client, job_id, lease, retryable, reason='failure'):
    with suppress(PlatformCallError):
        await client.fail(job_id, lease, retryable, reason)


async def run_job(client, settings, job):
    job_id, lease = job['id'], job['lease_token']
    kind = job.get('kind')
    if kind not in AGENTS:
        await _safe_fail(client, job_id, lease, False)
        return
    model = ReservedModel(settings, client, job_id, lease)
    graph = AGENTS[kind](kind, client, job, lease, model)
    config = {'configurable': {'thread_id': f"{job_id}:{job['attempts']}"}, 'recursion_limit': 30}
    execution = asyncio.create_task(graph.ainvoke({'kind': kind}, config))
    heartbeat = asyncio.create_task(_supervise_lease(client, job_id, lease, settings.heartbeat_seconds))
    try:
        async with asyncio.timeout(settings.deadline_seconds):
            done, _ = await asyncio.wait({execution, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                # Any lost or unconfirmed lease cancels the graph and prevents completion.
                heartbeat.result()
                return
            result = execution.result()['result']
            await client.heartbeat(job_id, lease)
            for attempt in range(2):
                try:
                    await client.complete(job_id, lease, result)
                    break
                except PlatformCallError as exc:
                    if exc.status != 503 or attempt:
                        raise
    except BudgetBlocked:
        await _safe_fail(client, job_id, lease, False, 'budget_blocked')
    except PlatformCallError as exc:
        if exc.status == 429:
            await _safe_fail(client, job_id, lease, False, 'budget_blocked')
        elif exc.status not in {401, 403, 409}:
            await _safe_fail(client, job_id, lease, exc.status >= 500)
    except (TimeoutError, ModelFailure):
        await _safe_fail(client, job_id, lease, True)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.error('Agent graph failed for job %s', job_id)
        await _safe_fail(client, job_id, lease, False)
    finally:
        for task in (execution, heartbeat):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task


async def serve(settings, client, stop):
    if not settings.enabled or not settings.llm_enabled:
        logger.info('Agent worker is disabled')
        return
    if not settings.platform_service_key.get_secret_value():
        raise RuntimeError('Agent Platform service key is required')
    route(settings)  # Do not advertise a worker with missing provider configuration.
    worker_id = uuid4()
    advertising = asyncio.create_task(_advertise(client, worker_id, stop))
    try:
        while not stop.is_set():
            try:
                response = await client.claim()
                job = response.get('job')
                if job:
                    running = asyncio.create_task(run_job(client, settings, job))
                    stopping = asyncio.create_task(stop.wait())
                    done, _ = await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
                    if stopping in done and not running.done():
                        running.cancel()
                    if not stopping.done():
                        stopping.cancel()
                    with suppress(asyncio.CancelledError):
                        await running
                    with suppress(asyncio.CancelledError):
                        await stopping
                    continue
            except PlatformCallError:
                logger.warning('Agent job claim failed')
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.poll_seconds)
            except TimeoutError:
                pass
    finally:
        stop.set()
        with suppress(asyncio.CancelledError):
            await advertising


async def _main():
    # Worker graphs do not send source text to external tracing services.
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    os.environ['LANGSMITH_TRACING'] = 'false'
    settings = Settings()
    client = HttpPlatformClient(settings.platform_url, settings.platform_service_key.get_secret_value())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for event in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(event, stop.set)
    try:
        await serve(settings, client, stop)
    finally:
        await client.close()


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
