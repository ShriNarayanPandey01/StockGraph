"""Rotating JSONL records for physical model calls; prompts and outputs are excluded."""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock

_lock = Lock()
_handlers: dict[Path, RotatingFileHandler] = {}


class _StrictRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record):
        error = sys.exc_info()[1]
        if error is not None:
            raise error


def write_model_usage(path: str, record: dict, *, max_bytes: int, backup_count: int) -> None:
    """Append one structured usage event and flush it to the local log file."""
    target = Path(path).expanduser().resolve()
    with _lock:
        handler = _handlers.get(target)
        if handler is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = _StrictRotatingFileHandler(
                target, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8', delay=False
            )
            handler.setFormatter(logging.Formatter('%(message)s'))
            _handlers[target] = handler
        message = json.dumps(record, ensure_ascii=False, separators=(',', ':'), default=str)
        handler.handle(logging.LogRecord('marketgraph_agents.usage', logging.INFO, '', 0, message, (), None))
        handler.flush()
