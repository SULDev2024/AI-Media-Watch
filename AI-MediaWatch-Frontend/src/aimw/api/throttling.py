"""In-process throttling primitives for the analyst API (C5 mitigation).

This module provides a single-flight gate and a rate-limited gate used
to protect ``POST /campaigns/recompute`` from queue-flooding abuse and
to keep ``GET /campaigns`` / ``GET /metrics`` from being used as a
graph-rebuild DDoS amplifier.

Scope: these are *process-local* primitives. They protect a single
Uvicorn instance, which is the pilot deployment topology
(docker-compose runs one ``api`` service). If the pilot scales to
multiple API replicas, this layer must be replaced by a Redis-backed
distributed lock — see deploy/ARCHITECTURE.md.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _InflightState:
    """Tracks a currently-running task's id and start time."""

    task_id: str
    started_at: float


class SingleFlightGate:
    """Single-flight gate that admits at most one in-flight invocation.

    Used by ``POST /campaigns/recompute`` to coalesce concurrent
    recompute requests onto a single Celery task.  While a task is
    in-flight, additional requests get back the existing task id
    instead of enqueueing a fresh one.

    The gate has a TTL.  After ``ttl_seconds`` from when the slot was
    claimed, the slot is considered stale and the next caller may claim
    a new one — this prevents a hung worker or a missed completion
    signal from permanently locking the endpoint.
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._state: _InflightState | None = None

    def try_claim(self, task_id: str) -> tuple[bool, str]:
        """Try to register ``task_id`` as the in-flight task.

        Returns
        -------
        (claimed, task_id_to_report)
            ``claimed`` is True iff this call became the in-flight slot.
            ``task_id_to_report`` is what the API should hand back to
            the caller — either the newly claimed id, or the existing
            in-flight id if the slot was already taken.
        """
        now = time.monotonic()
        with self._lock:
            if self._state is not None and now - self._state.started_at < self._ttl:
                return False, self._state.task_id
            self._state = _InflightState(task_id=task_id, started_at=now)
            return True, task_id

    def release(self, task_id: str) -> None:
        """Mark the in-flight task complete iff its id matches the current slot."""
        with self._lock:
            if self._state is not None and self._state.task_id == task_id:
                self._state = None

    # Test helpers --------------------------------------------------------

    def _force_clear(self) -> None:  # pragma: no cover - test-only
        with self._lock:
            self._state = None

    def _current(self) -> _InflightState | None:  # pragma: no cover - test-only
        with self._lock:
            return self._state


class TokenBucketGate:
    """Per-route token bucket for low-cost rate limiting.

    Used to throttle ``GET /campaigns`` and ``GET /metrics`` which both
    run a full graph rebuild on each request (H1).  The bucket grants
    ``capacity`` tokens, refilled at ``refill_per_second`` tokens/sec.
    Each successful request consumes one token; when the bucket is
    empty the request is rejected.

    The bucket is keyed by a string identifier so different routes get
    independent buckets — and so a future per-client-id extension can
    plug in without API changes.
    """

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self._capacity = float(capacity)
        self._refill_rate = refill_per_second
        self._lock = threading.Lock()
        self._tokens: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def try_consume(self, key: str = "default") -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last.get(key, now)
            tokens = self._tokens.get(key, self._capacity)
            elapsed = max(0.0, now - last)
            tokens = min(self._capacity, tokens + elapsed * self._refill_rate)
            self._last[key] = now
            if tokens >= 1.0:
                self._tokens[key] = tokens - 1.0
                return True
            self._tokens[key] = tokens
            return False

    def _reset(self) -> None:  # pragma: no cover - test-only
        with self._lock:
            self._tokens.clear()
            self._last.clear()


# Process-wide singletons — wired into the routers via module reference.
recompute_gate = SingleFlightGate(ttl_seconds=60.0)
# /campaigns and /metrics share a generous bucket: 30 req/min steady-state,
# bursts up to 10 requests. Pilot traffic is sub-pilot; production tuning
# will replace these constants with settings-driven values.
campaigns_bucket = TokenBucketGate(capacity=10, refill_per_second=0.5)
metrics_bucket = TokenBucketGate(capacity=10, refill_per_second=0.5)


__all__ = [
    "SingleFlightGate",
    "TokenBucketGate",
    "campaigns_bucket",
    "metrics_bucket",
    "recompute_gate",
]
