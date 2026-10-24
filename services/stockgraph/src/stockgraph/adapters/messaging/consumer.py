"""At-least-once Redis Streams consumption with pending recovery and single flight."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError
from redis.exceptions import ResponseError
from stockgraph.domain.events import CommittedEvent
from stockgraph.runtime.settings import settings

logger = logging.getLogger(__name__)


@contextmanager
def renewable_lock(redis: Any):
    # Registry refreshes and news routing mutate the same exposure graph. One graph writer
    # avoids racing interval rotation, including when multiple worker replicas run.
    lock = redis.lock(
        "stockgraph:graph-writer",
        timeout=settings.event_lease_seconds,
        blocking_timeout=0,
        thread_local=False,
    )
    if not lock.acquire(blocking=False):
        yield False
        return
    stopped = threading.Event()
    lost = threading.Event()

    def renew() -> None:
        while not stopped.wait(settings.event_lease_seconds / 3):
            try:
                lock.extend(settings.event_lease_seconds, replace_ttl=True)
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()

    def ensure_owned() -> None:
        if lost.is_set() or not lock.owned():
            raise RuntimeError("Graph writer lease was lost; refusing graph writes")

    try:
        yield ensure_owned
        ensure_owned()
    finally:
        stopped.set()
        thread.join(timeout=1)
        try:
            lock.release()
        except Exception:
            pass  # Never acknowledge an event solely because a lease expired.


class EventConsumer:
    def __init__(self, redis: Any, pipeline: Any, consumer_name: str | None = None) -> None:
        self._redis, self._pipeline = redis, pipeline
        self._name = consumer_name or f"graph-{uuid.uuid4().hex[:12]}"
        self._claim_cursor = "0-0"

    def ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(
                settings.event_stream, settings.event_consumer_group, "0-0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_once(self, block_ms: int = 1000) -> int:
        recovered = self._redis.xautoclaim(
            settings.event_stream,
            settings.event_consumer_group,
            self._name,
            settings.event_retry_idle_ms,
            start_id=self._claim_cursor,
            count=1,
        )
        self._claim_cursor = recovered[0]
        messages = list(recovered[1])
        # Always admit new work as well as retries, even when pending work is
        # permanently broken or inference takes longer than the claim interval.
        if hasattr(self._redis, "xreadgroup"):
            kwargs = {"count": 1}
            if not messages:
                kwargs["block"] = block_ms
            batches = self._redis.xreadgroup(
                settings.event_consumer_group,
                self._name,
                {settings.event_stream: ">"},
                **kwargs,
            )
            messages.extend(message for _, entries in batches for message in entries)
        processed = 0
        for message_id, fields in messages:
            due = self._redis.hget(self._retry_key(message_id), "next_attempt_at")
            if due is not None and float(due) > time.time():
                continue
            if self.handle(message_id, fields):
                processed += 1
        return processed

    def handle(self, message_id: str, fields: dict) -> bool:
        event: CommittedEvent | None = None
        try:
            event = CommittedEvent.model_validate_json(fields.get("event") or fields.get(b"event"))
            done_key = f"stockgraph:event:{event.event_id}"
            if self._redis.hget(done_key, "state") in ("completed", b"completed"):
                self._ack(message_id)
                return True
            with renewable_lock(self._redis) as acquired:
                if not acquired:
                    return False
                repo = self._pipeline._repo
                if callable(acquired) and hasattr(repo, "set_write_guard"):
                    repo.set_write_guard(acquired)
                try:
                    self._state(event, "graph_processing")
                    self._pipeline.process(event)
                except Exception as exc:
                    if callable(acquired):
                        acquired()  # Do not let an expired lease overwrite another worker.
                    error = f"{type(exc).__name__}: graph processing failed; event remains queued for retry"
                    from stockgraph.adapters.llm.base import BudgetExceeded, LLMDisabled

                    if isinstance(exc, (BudgetExceeded, LLMDisabled)):
                        error = str(exc)
                    quarantined = self._record_failure(message_id, fields, event, exc, "inference")
                    self._state(event, "quarantined" if quarantined else "failed", error)
                    if event.kind == "registry.updated" and event.payload.get("kind") in (
                        "Stock",
                        "Commodity",
                        "MacroFactor",
                        "Sector",
                    ):
                        repo.mark_entity_failed(event.payload["kind"], event.entity_id)
                    return quarantined
                finally:
                    if hasattr(repo, "set_write_guard"):
                        repo.set_write_guard(None)
            self._state(event, "completed")
            self._ack(message_id)
            return True
        except Exception as exc:
            # A failed entry stays in the pending-entry list; XAUTOCLAIM retries it
            # after the idle delay even if the original worker has disappeared.
            error = f"{type(exc).__name__}: graph processing failed; inspect worker diagnostics and retry"
            if callable(locals().get("acquired")):
                try:
                    acquired()
                except Exception:
                    return False  # A stale owner cannot overwrite a replacement worker's status.
            quarantined = self._record_failure(
                message_id, fields, event, exc, "validation" if event is None else "projection"
            )
            if event:
                self._state(event, "quarantined" if quarantined else "failed", error)
                if event.kind == "registry.updated" and event.payload.get("kind") in (
                    "Stock",
                    "Commodity",
                    "MacroFactor",
                    "Sector",
                ):
                    self._pipeline._repo.mark_entity_failed(event.payload["kind"], event.entity_id)
            else:
                self._redis.hset("stockgraph:invalid-events", str(message_id), error)
            return quarantined

    @staticmethod
    def _retry_key(message_id) -> str:
        if isinstance(message_id, bytes):
            message_id = message_id.decode()
        return f"stockgraph:event-retry:{message_id}"

    def _record_failure(self, message_id, fields, event, exc, stage) -> bool:
        key = self._retry_key(message_id)
        attempts = int(self._redis.hget(key, "attempts") or 0) + 1
        frames = traceback.extract_tb(exc.__traceback__)
        # Log location and exception class without provider URLs, credentials,
        # model prompts or article bodies from exception messages.
        diagnostic = " <- ".join(f"{frame.name}:{frame.lineno}" for frame in frames)
        logger.error(
            "Graph event %s failed stage=%s attempts=%s exception=%s stack=%s",
            str(event.event_id) if event else message_id,
            stage,
            attempts,
            type(exc).__name__,
            diagnostic,
        )
        self._redis.hset(
            key,
            mapping={
                "attempts": attempts,
                "failure_stage": stage,
                "exception_type": type(exc).__name__,
                "next_attempt_at": time.time() + min(3600, 2 ** min(attempts, 11)),
            },
        )
        permanent = isinstance(exc, (ValidationError, KeyError, ValueError, TypeError))
        maximum = getattr(settings, "event_permanent_max_attempts", 3)
        if event is not None and not (permanent and attempts >= maximum):
            return False
        # Quarantine retains the untouched wire body for explicit replay. ACK
        # follows durable XADD; if that fails the original stays pending.
        payload = fields.get("event") or fields.get(b"event") or ""
        writer = (
            self._redis.pipeline(transaction=True)
            if hasattr(self._redis, "pipeline")
            else self._redis
        )
        writer.xadd(
            f"{settings.event_stream}:quarantine",
            {
                "event": payload,
                "original_message_id": message_id,
                "failure_stage": stage,
                "exception_type": type(exc).__name__,
                "attempts": attempts,
            },
        )
        writer.hset(key, mapping={"state": "quarantined"})
        writer.xack(settings.event_stream, settings.event_consumer_group, message_id)
        if writer is not self._redis:
            writer.execute()
        return True

    def _state(self, event: CommittedEvent, state: str, error: str = "") -> None:
        mapping = {"state": state, "error": error, "entity_id": event.entity_id}
        writer = (
            self._redis.pipeline(transaction=True)
            if hasattr(self._redis, "pipeline")
            else self._redis
        )
        writer.hset(f"stockgraph:event:{event.event_id}", mapping=mapping)
        if event.job_id:
            writer.hset(
                f"stockgraph:job:{event.job_id}", mapping={**mapping, "ticker": event.entity_id}
            )
        if writer is not self._redis:
            writer.execute()

    def _ack(self, message_id: str) -> None:
        self._redis.xack(settings.event_stream, settings.event_consumer_group, message_id)
