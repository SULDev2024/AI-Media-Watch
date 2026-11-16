"""Celery task definitions for Phase 13.

Every task body is a one-liner: route the coroutine through
:func:`aimw.workers.runner.run_async`. No ``asyncio.run`` calls.
No business logic. The pipeline / graph / regression-suite
implementations live in their own modules.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, TypeVar

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aimw.db.models import PipelineMetricsRow
from aimw.db.session import get_sessionmaker, writer_lock
from aimw.workers.celery_app import celery_app
from aimw.workers.runner import run_async

_LOG = logging.getLogger("aimw.workers.tasks")
_YOUTUBE_QUERY_CONCURRENCY = 4
_TELEGRAM_QUERY_CONCURRENCY = 2
_T = TypeVar("_T")


@celery_app.task(  # type: ignore[misc, has-type]
    bind=True,
    name="aimw.workers.tasks.process_video",
    max_retries=2,
    default_retry_delay=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_video(self: Any, video_id: str) -> str:
    """Drain one ingest_queue row → end-to-end pipeline → report_id.

    Per ADR-0002 the body funnels the coroutine through ``run_async``;
    failures persist a ``status="failed"`` package (see
    :func:`aimw.workers.pipeline.run_pipeline`) and then re-raise so
    Celery's retry policy applies.
    """
    from aimw.workers.pipeline import run_pipeline

    try:
        return run_async(run_pipeline(video_id))
    except Exception as exc:
        _LOG.exception("process_video failed", extra={"video_id": video_id})
        # Persist-failure is already done inside run_pipeline; here we
        # just delegate to Celery's retry policy for transient errors.
        raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1)) from exc


@celery_app.task(  # type: ignore[misc, has-type]
    bind=True,
    name="aimw.workers.tasks.recompute_campaigns",
    max_retries=3,
    default_retry_delay=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def recompute_campaigns(self: Any, min_videos: int = 3) -> int:
    """Phase 11 graph recompute — beat-driven every 600 s (Phase 13 wiring).

    Returns the number of packages whose evidence was promoted.

    Compatibility:
        Preserves the production-hardening behaviour of the prior
        implementation (retry policy, structured duration / failure
        metrics) so existing dashboards and tests do not regress.
    """
    import time

    from aimw.observability.metrics import (
        emit_celery_task_duration,
        emit_celery_task_failure,
    )

    async def _go() -> int:
        from aimw.graph import builder, campaigns, feedback

        sm = get_sessionmaker()
        graph = await builder.build_from_db(sm)
        found = list(campaigns.find(graph, min_videos=min_videos))
        if not found:
            return 0
        return await feedback.promote(sm, found)

    t0 = time.monotonic()
    try:
        result = run_async(_go())
        emit_celery_task_duration(
            "recompute_campaigns", time.monotonic() - t0, "SUCCESS"
        )
        return result
    except Exception as exc:
        emit_celery_task_failure("recompute_campaigns", type(exc).__name__)
        emit_celery_task_duration(
            "recompute_campaigns", time.monotonic() - t0, "FAILURE"
        )
        raise self.retry(
            exc=exc, countdown=2 ** (self.request.retries + 1)
        ) from exc


async def _telegram_search(
    sm: Any, queries: list[str], per_query: int, content_types: list[str] | None = None
) -> int:
    """Run Telegram global search for each query — downloads text, photos, videos."""
    from aimw.collection.telegram_search import search_and_collect
    from aimw.core.config import get_settings
    from aimw.db.repositories.videos import VideosRepository
    from aimw.workers.enqueue import enqueue_prepared

    cfg = get_settings()
    if not cfg.telegram_api_id or not cfg.telegram_api_hash or not cfg.telegram_session:
        _LOG.warning("telegram_search_skip", extra={"reason": "credentials not configured"})
        return 0

    api_id = cfg.telegram_api_id
    api_hash = cfg.telegram_api_hash.get_secret_value()
    session_str = cfg.telegram_session.get_secret_value()
    media_dir = cfg.resolved_media_dir
    repo = VideosRepository(sm)
    enqueued = 0
    known_urls = await repo.known_urls('telegram')

    for query in queries:
        try:
            items = await search_and_collect(
                query,
                api_id=api_id,
                api_hash=api_hash,
                session_str=session_str,
                media_dir=media_dir,
                limit=per_query,
                content_types=content_types,
                exclude_urls=known_urls,
            )
        except Exception:
            _LOG.warning("telegram_search_query_failed", extra={"query": query})
            continue

        for item in items:
            video_id = item["video_id"]
            if await repo.get(video_id) is not None:
                continue
            try:
                await enqueue_prepared(
                    sm,
                    video_id=video_id,
                    url=item["url"],
                    platform=item["platform"],
                    raw_path=item["raw_path"],
                )
                enqueued += 1
            except Exception:
                _LOG.warning(
                    "collector_enqueue_failed",
                    extra={"video_id": video_id, "platform": "telegram"},
                )

    _LOG.info("telegram_search_done", extra={"enqueued": enqueued, "queries": len(queries)})
    return enqueued


async def _gather_limited(
    items: list[_T],
    limit: int,
    fn: Any,
) -> list[Any]:
    """Run ``fn(item)`` for each item with a bounded concurrency cap."""
    if not items:
        return []

    sem = asyncio.Semaphore(max(1, min(limit, len(items))))

    async def _run(item: _T) -> Any:
        async with sem:
            return await fn(item)

    return await asyncio.gather(*(_run(item) for item in items))


@celery_app.task(  # type: ignore[misc, has-type]
    bind=True,
    name="aimw.workers.tasks.collector_tick",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
)
def collector_tick(self: Any) -> int:
    return run_async(collect_once())


async def collect_once() -> int:
    """One crawl cycle: a no-op when stopped, else discover + enqueue.

    Beat fires this every :data:`COLLECTOR_TICK_INTERVAL_SECONDS`. When the
    admin has the collector ``running``, each configured query is searched
    and any *new* candidate (no existing ``videos`` row) is enqueued for the
    normal pipeline. Returns the number of new videos enqueued this tick.

    A tick must never crash the worker — discovery failures are already
    swallowed in :func:`aimw.collection.collector.search_candidates`; here we
    guard the enqueue loop and always stamp the run so the dashboard updates.
    """
    from aimw.collection import control
    from aimw.collection.collector import search_candidates
    from aimw.collection.search_plan import expand_queries
    from aimw.workers.enqueue import enqueue_video_url

    state = control.get_state()
    if state.get("status") != "running":
        return 0

    lock_token = control.acquire_tick_lock()
    if lock_token is None:
        _LOG.info("collector_tick_skipped", extra={"reason": "already_running"})
        return 0

    queries: list[str] = state.get("queries") or []
    per_query: int = int(state.get("per_query", 5))
    platforms: list[str] = state.get("platforms") or ["youtube"]
    content_types: list[str] = state.get("content_types") or ["video", "photo", "text"]
    region_focus: str = state.get("region_focus") or "global"

    try:
        if not queries:
            _LOG.info("collector_tick_idle", extra={"reason": "no_queries"})
            return 0

        search_queries = expand_queries(queries, region_focus=region_focus)

        supported = control.supported_platforms()
        active = [p for p in platforms if p in supported]
        skipped = [p for p in platforms if p not in supported]
        if skipped:
            _LOG.info("collector_platforms_unsupported", extra={"skipped": skipped})
        if not active:
            control.record_run(0)
            return 0

        async def _go() -> int:
            sm = get_sessionmaker()
            enqueued = 0

            # YouTube keyword search (yt-dlp, always available). YouTube candidates
            # are videos, so only crawl it when "video" is among the chosen kinds.
            if "youtube" in active and "video" in content_types:
                seen_youtube_urls: set[str] = set()
                youtube_searches = await _gather_limited(
                    search_queries,
                    _YOUTUBE_QUERY_CONCURRENCY,
                    lambda query: asyncio.to_thread(search_candidates, query, per_query),
                )
                for urls in youtube_searches:
                    for url in urls:
                        if not control.is_running():
                            break
                        if url in seen_youtube_urls:
                            continue
                        seen_youtube_urls.add(url)
                        try:
                            _vid, queue_id = await enqueue_video_url(
                                sm, url, skip_if_exists=True
                            )
                        except Exception:
                            _LOG.warning("collector_enqueue_failed", extra={"url": url})
                            continue
                        if queue_id is not None:
                            enqueued += 1

            # Telegram global keyword search (Telethon, needs session). The chosen
            # content kinds filter which messages are downloaded + enqueued.
            if "telegram" in active:
                telegram_runs = await _gather_limited(
                    search_queries,
                    _TELEGRAM_QUERY_CONCURRENCY,
                    lambda query: _telegram_search(sm, [query], per_query, content_types),
                )
                enqueued += sum(telegram_runs)

            return enqueued

        enqueued = await _go()
        control.record_run(enqueued)
        _LOG.info(
            "collector_tick_done",
            extra={
                "enqueued": enqueued,
                "queries": len(queries),
                "searches": len(search_queries),
                "region_focus": region_focus,
            },
        )
        return enqueued
    finally:
        control.release_tick_lock(lock_token)


@celery_app.task(  # type: ignore[misc, has-type]
    name="aimw.workers.tasks.replay_regression_suite",
    acks_late=True,
    reject_on_worker_lost=True,
)
def replay_regression_suite() -> dict[str, float]:
    """Run the §11 ambiguity benchmark suite and store the results.

    Writes one row to ``pipeline_metrics`` per invocation so the
    Phase 12 ``/api/v1/metrics/precision-recall`` endpoint and any
    future dashboards can read historical performance.
    """

    async def _go() -> dict[str, float]:
        from pathlib import Path

        from tests.benchmark.loader import load_corpus
        from tests.benchmark.runner import run as benchmark_run

        manifest = (
            Path(__file__).resolve().parents[3]
            / "tests" / "benchmark" / "corpus" / "manifest.yaml"
        )
        cases = load_corpus(manifest)
        bm = benchmark_run(cases)
        metrics = {
            "n_cases": float(bm.n_cases),
            "precision": bm.binary.precision,
            "recall": bm.binary.recall,
            "f1": bm.binary.f1,
        }
        now = dt.datetime.now(dt.UTC)
        sm = get_sessionmaker()
        async with writer_lock(), sm() as session, session.begin():
            stmt = sqlite_insert(PipelineMetricsRow).values(
                metric_name="precision_recall",
                metric_value=bm.binary.f1,
                payload=metrics,
                created_at=now,
            )
            await session.execute(stmt)
        return metrics

    return run_async(_go())


@celery_app.task(  # type: ignore[misc, has-type]
    name="aimw.workers.tasks.refresh_keyword_suggestions",
    acks_late=True,
    reject_on_worker_lost=True,
)
def refresh_keyword_suggestions() -> int:
    """Regenerate auto-keyword suggestions from flagged content.

    Beat fires this every hour. Reads HIGH/CRITICAL verdicts, extracts
    common scam patterns, and optionally asks the LLM for search terms
    that would catch similar content.
    """
    from aimw.collection import control
    from aimw.workers.keyword_suggest import generate_suggestions

    state = control.get_state()
    current_queries = state.get("queries") or []

    async def _go() -> int:
        suggestions = await generate_suggestions(existing_keywords=current_queries)
        return len(suggestions)

    try:
        count = run_async(_go())
        _LOG.info("keyword_suggestions_refreshed", extra={"count": count})
        return count
    except Exception as exc:
        _LOG.warning("keyword_suggestions_failed", extra={"error": str(exc)})
        return 0


__all__ = [
    "collector_tick",
    "process_video",
    "recompute_campaigns",
    "refresh_keyword_suggestions",
    "replay_regression_suite",
]
