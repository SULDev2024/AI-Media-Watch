"""Metric events emitted via standard Python logging.

Each function emits a single ``LogRecord`` with a ``metric`` extra field that
log aggregators (Grafana Loki, Datadog, ELK) can index on to build dashboards.
At DEBUG level (the default for ``emit_signal_distribution``,
``emit_ocr_confidence_stats``, ``emit_entity_extraction_counts``, and
``emit_campaign_size_distribution``) the calls are near-zero-cost when the
handler level is above DEBUG.

Designed to be called from any AIMW subsystem without violating import-linter
contracts: this module imports only the standard library.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

_LOG = logging.getLogger("aimw.metrics")


def emit_signal_distribution(counts: dict[str, int], total: int) -> None:
    """Per-package indicator-type distribution for drift detection.

    A ≥20% week-over-week drop in any indicator type may signal tactic evasion
    or a broken entry in the signal catalog.
    """
    _LOG.debug(
        "signal_distribution",
        extra={"metric": "signal_distribution", "counts": counts, "total": total},
    )


def emit_ocr_confidence_stats(
    confidences: Sequence[float],
    low_threshold: float = 0.7,
) -> None:
    """OCR block confidence distribution for extraction-quality monitoring."""
    if not confidences:
        return
    n = len(confidences)
    n_low = sum(1 for c in confidences if c < low_threshold)
    _LOG.debug(
        "ocr_confidence_stats",
        extra={
            "metric": "ocr_confidence",
            "n_blocks": n,
            "n_low_confidence": n_low,
            "min_confidence": round(min(confidences), 4),
            "max_confidence": round(max(confidences), 4),
            "mean_confidence": round(sum(confidences) / n, 4),
        },
    )


def emit_entity_extraction_counts(
    n_wallets: int,
    n_phones: int,
    n_handles: int,
    n_links: int,
    n_referral_codes: int,
) -> None:
    """Entity counts per package for extraction-recall monitoring."""
    _LOG.debug(
        "entity_extraction_counts",
        extra={
            "metric": "entity_extraction",
            "n_wallets": n_wallets,
            "n_phones": n_phones,
            "n_handles": n_handles,
            "n_links": n_links,
            "n_referral_codes": n_referral_codes,
        },
    )


def emit_token_budget_fallback() -> None:
    """Emitted when token budget exhaustion routes a package to analyst_review."""
    _LOG.warning(
        "token_budget_fallback",
        extra={"metric": "token_budget_fallback"},
    )


def emit_confidence_softened(
    original_level: str,
    new_level: str,
    confidence: float,
) -> None:
    """Emitted when low confidence softens a HIGH/CRITICAL verdict one step."""
    _LOG.info(
        "confidence_softened",
        extra={
            "metric": "confidence_softened",
            "original_level": original_level,
            "new_level": new_level,
            "confidence": round(confidence, 4),
        },
    )


def emit_campaign_size_distribution(sizes: Sequence[int]) -> None:
    """Campaign size distribution for detection-threshold calibration."""
    if not sizes:
        return
    _LOG.debug(
        "campaign_size_distribution",
        extra={
            "metric": "campaign_sizes",
            "n_campaigns": len(sizes),
            "sizes": list(sorted(sizes)),
            "max_size": max(sizes),
        },
    )


def emit_collection_failure(platform: str, url: str, reason: str) -> None:
    """Emitted when a collection attempt fails (network, auth, format error)."""
    _LOG.error(
        "collection_failure",
        extra={
            "metric": "collection_failure",
            "platform": platform,
            "url": url,
            "reason": reason,
        },
    )


def emit_celery_task_duration(task_name: str, duration_s: float, status: str) -> None:
    """Task wall-clock duration in seconds (SUCCESS or FAILURE)."""
    _LOG.info(
        "celery_task_duration",
        extra={
            "metric": "celery_task_duration",
            "task_name": task_name,
            "duration_s": round(duration_s, 3),
            "status": status,
        },
    )


def emit_celery_task_failure(task_name: str, exc_type: str) -> None:
    """Emitted when a Celery task terminates with an unhandled exception."""
    _LOG.error(
        "celery_task_failure",
        extra={
            "metric": "celery_task_failure",
            "task_name": task_name,
            "exc_type": exc_type,
        },
    )


def emit_db_write_latency(operation: str, duration_s: float) -> None:
    """Repository write latency (operation = 'save_package', 'record_feedback', …)."""
    _LOG.debug(
        "db_write_latency",
        extra={
            "metric": "db_write_latency",
            "operation": operation,
            "duration_s": round(duration_s, 6),
        },
    )


def emit_groq_request_result(model: str, tokens_used: int, success: bool) -> None:
    """Groq API call outcome — tokens consumed and whether the call succeeded."""
    level = logging.DEBUG if success else logging.WARNING
    _LOG.log(
        level,
        "groq_request_result",
        extra={
            "metric": "groq_request_result",
            "model": model,
            "tokens_used": tokens_used,
            "success": success,
        },
    )
