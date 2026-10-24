"""Independent evidence stream, sharing the global guarded graph writer."""

import logging
import time
from uuid import uuid4

from pydantic import ValidationError
from redis.exceptions import ResponseError
from stockgraph.adapters.messaging.consumer import renewable_lock
from stockgraph.domain.platform_events import PlatformEvent
from stockgraph.runtime.settings import settings


class PlatformConsumer:
    def __init__(self, redis, pipeline):
        self.redis, self.pipeline = redis, pipeline
        self.stream = getattr(settings, "platform_stream_name", "stockgraph:platform-events:v1")
        self.group = getattr(settings, "platform_consumer_group", "stockgraph-platform-v1")
        self.name, self.cursor = f"evidence-{uuid4().hex[:12]}", "0-0"

    def ensure_group(self):
        try:
            self.redis.xgroup_create(self.stream, self.group, "0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_once(self, block_ms=50):
        recovered = self.redis.xautoclaim(self.stream, self.group, self.name,
                                        settings.event_retry_idle_ms, start_id=self.cursor, count=1)
        self.cursor, messages = recovered[0], list(recovered[1])
        if hasattr(self.redis, "xreadgroup"):
            kwargs = {"count": 1}
            if not messages:
                kwargs["block"] = block_ms
            batches = self.redis.xreadgroup(self.group, self.name, {self.stream: ">"},
                                           **kwargs)
            messages.extend(message for _, entries in batches for message in entries)
        count = 0
        for message_id, fields in messages:
            due = self.redis.hget(self._retry_key(message_id), "next_attempt_at")
            if due is not None and float(due) > time.time():
                continue
            event = None
            guard = None
            try:
                event = PlatformEvent.model_validate_json(fields.get("event") or fields.get(b"event"))
                state_key = f"stockgraph:platform-event:{event.event_id}"
                if self.redis.hget(state_key, "state") not in ("completed", b"completed"):
                    with renewable_lock(self.redis) as guard:
                        if not guard:
                            continue
                        self.pipeline._repo.set_write_guard(guard)
                        try:
                            self.pipeline.process(event)
                            guard()
                            self.redis.hset(state_key, mapping={"state": "completed", "error": ""})
                        except Exception as exc:
                            guard()
                            quarantined = self._failure(message_id, fields, event, exc)
                            self.redis.hset(state_key,
                                mapping={"state": "quarantined" if quarantined else "failed",
                                         "error": "Projection requires replay" if quarantined else "Projection pending retry"})
                            if quarantined:
                                count += 1
                            continue
                        finally:
                            self.pipeline._repo.set_write_guard(None)
                self.redis.xack(self.stream, self.group, message_id)
                count += 1
            except Exception as exc:
                # Keep pending until corrected/replayed. Do not log submitted document bodies.
                logging.error("Evidence projection failed (%s); pending entry %s is retained",
                              type(exc).__name__, message_id)
                # A failed writer must not change state after its lease was lost.
                # Envelope errors do not need a writer lease and are quarantined immediately.
                if event is None and self._failure(message_id, fields, None, exc):
                    count += 1
        return count

    def _retry_key(self, message_id):
        if isinstance(message_id, bytes):
            message_id = message_id.decode()
        return f"stockgraph:platform-retry:{message_id}"

    def _failure(self, message_id, fields, event, exc):
        key = self._retry_key(message_id)
        attempts = int(self.redis.hget(key, "attempts") or 0) + 1
        logging.error("Evidence entry %s failed exception=%s attempts=%s",
                      message_id, type(exc).__name__, attempts)
        self.redis.hset(key, mapping={"attempts": attempts, "exception_type": type(exc).__name__,
            "next_attempt_at": time.time() + min(3600, 2 ** min(attempts, 11))})
        # Missing canonical projections may be waiting behind source events for
        # arbitrarily long outages. Never quarantine them merely after retries.
        permanent = isinstance(exc, (ValidationError, ValueError, TypeError))
        if event is not None and not (permanent and attempts >= getattr(settings, "event_permanent_max_attempts", 3)):
            return False
        writer = self.redis.pipeline(transaction=True) if hasattr(self.redis, "pipeline") else self.redis
        writer.xadd(f"{self.stream}:quarantine", {
            "event": fields.get("event") or fields.get(b"event") or "",
            "original_message_id": message_id, "exception_type": type(exc).__name__, "attempts": attempts})
        writer.hset(key, mapping={"state": "quarantined"})
        writer.xack(self.stream, self.group, message_id)
        if writer is not self.redis:
            writer.execute()
        return True
