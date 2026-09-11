"""Monotonic operation timing propagated through async tasks and thread pools."""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class OperationTiming:
    started: float
    request_id: str | None = None


current_operation: ContextVar[OperationTiming | None] = ContextVar("audit_operation", default=None)


@contextmanager
def measure_operation(*, request_id=None, timing=None):
    """Nested service calls retain the request's start; standalone jobs get their own."""
    current = current_operation.get()
    if current is not None:
        yield current
        return
    operation = timing or OperationTiming(time.monotonic(), request_id)
    token = current_operation.set(operation)
    try:
        yield operation
    finally:
        current_operation.reset(token)


def elapsed_ms():
    operation = current_operation.get()
    return round(max(0, time.monotonic() - operation.started) * 1000, 1) if operation else None
