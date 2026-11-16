"""Redis-backed sliding-window rate limiter."""

from __future__ import annotations

import time
import logging

_LOG = logging.getLogger("aimw.api.rate_limit")


def _get_redis():
    try:
        import redis

        from aimw.core.config import get_settings

        return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    except Exception:
        return None


def check_rate_limit(key: str, limit: int = 10, window: int = 60) -> bool:
    """Return True if the request is within the rate limit."""
    r = _get_redis()
    if r is None:
        return True

    redis_key = f"aimw:rate:{key}"
    now = time.time()

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - window)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window + 10)
        results = pipe.execute()
        count = results[2]
        return count <= limit
    except Exception:
        _LOG.warning("rate_limit_redis_error", exc_info=True)
        return True
