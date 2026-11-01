"""Bounded, redacted provider diagnostics. Never expose through the public API."""
from __future__ import annotations

import contextvars
import functools
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import db_path

_context = contextvars.ContextVar("planner_diagnostics", default={})
_lock = threading.Lock()


def redact(value):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if re.search(r"key|token|password|authorization|cookie|secret|email|phone|booking_request", str(k), re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"https?://[^\s\"<>]+", lambda m: re.match(r"https?://[^/?#]+", m.group(0)).group(0) + "/[REDACTED]", value)[:20000]
    return value


def event(name, **fields):
    try:
        with _lock:
            logger = logging.getLogger("planner.provider_diagnostics")
            if not logger.handlers:
                directory = Path(db_path()).parent / "logs"
                directory.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(directory / "api-debug.jsonl", maxBytes=5*1024*1024, backupCount=4, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
                logger.propagate = False
        record = redact({"time": datetime.now(timezone.utc).isoformat(), "event": name, **_context.get(), **fields})
        encoded = json.dumps(record, ensure_ascii=False, default=str)
        if len(encoded) > 100000:
            record = {"time": record["time"], "event": name, "context": redact(_context.get()), "truncated": True, "preview": encoded[:90000]}
            encoded = json.dumps(record, ensure_ascii=False)
        logger.info(encoded)
    except (OSError, ValueError, TypeError):
        logging.getLogger(__name__).warning("Planner diagnostics could not be written")


def operation(stage):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            token = _context.set({"query_id": uuid.uuid4().hex, "stage": stage})
            started = time.monotonic()
            event("operation_started")
            try:
                result = fn(*args, **kwargs)
                event("operation_completed", duration_ms=round((time.monotonic()-started)*1000), result=result)
                return result
            except Exception as exc:
                event("operation_failed", error_type=type(exc).__name__)
                raise
            finally:
                _context.reset(token)
        return wrapped
    return decorate


def provider_call(provider, method, request, invoke):
    started = time.monotonic()
    call_id = uuid.uuid4().hex
    event("provider_request", call_id=call_id, provider=provider, method=method, request=request)
    try:
        result = invoke()
        event("provider_response", call_id=call_id, provider=provider, method=method,
              duration_ms=round((time.monotonic()-started)*1000), response=result)
        return result
    except Exception as exc:
        event("provider_failed", call_id=call_id, provider=provider, method=method,
              duration_ms=round((time.monotonic()-started)*1000), error_type=type(exc).__name__, status_code=getattr(exc, "code", None))
        raise


class InstrumentedClient:
    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        value = getattr(self._client, name)
        if not callable(value):
            return value
        @functools.wraps(value)
        def call(*args, **kwargs):
            return provider_call("ignav", name, {"arguments": "[OMITTED]" if args else None, **kwargs}, lambda: value(*args, **kwargs))
        return call
