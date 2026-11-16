"""Celery beat schedule for Phase 13.

Single source of truth for periodic task wiring.  Imported by
``aimw.workers.celery_app`` so the schedule is registered as soon as
the worker app is constructed.
"""
from __future__ import annotations

from typing import Any

# §15 cadence: 10 minutes between graph rebuilds.  This is the
# operative number from the spec — keep in sync with the test that
# asserts it.
RECOMPUTE_CAMPAIGNS_INTERVAL_SECONDS: float = 600.0

# Collector crawl cadence. The tick is a no-op while the admin has the
# collector stopped, so a tight interval is cheap; 120 s keeps newly
# discovered videos flowing without hammering YouTube search.
COLLECTOR_TICK_INTERVAL_SECONDS: float = 120.0

# Auto-keyword suggestions refresh every hour.
KEYWORD_SUGGEST_INTERVAL_SECONDS: float = 3600.0


def build_schedule() -> dict[str, dict[str, Any]]:
    """Return the dict assigned to ``celery_app.conf.beat_schedule``."""
    return {
        "campaigns": {
            "task": "aimw.workers.tasks.recompute_campaigns",
            "schedule": RECOMPUTE_CAMPAIGNS_INTERVAL_SECONDS,
        },
        "collector": {
            "task": "aimw.workers.tasks.collector_tick",
            "schedule": COLLECTOR_TICK_INTERVAL_SECONDS,
        },
        "keyword_suggestions": {
            "task": "aimw.workers.tasks.refresh_keyword_suggestions",
            "schedule": KEYWORD_SUGGEST_INTERVAL_SECONDS,
        },
    }


__all__ = [
    "RECOMPUTE_CAMPAIGNS_INTERVAL_SECONDS",
    "COLLECTOR_TICK_INTERVAL_SECONDS",
    "build_schedule",
]
