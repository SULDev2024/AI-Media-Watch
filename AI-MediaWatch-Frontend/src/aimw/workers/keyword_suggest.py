"""Worker-layer keyword suggestion — LLM expansion + DB reads.

This module is allowed to import reasoning, DB, and other internals
because it lives in the workers layer (not collection). It orchestrates:

1. Read flagged content from the DB
2. Run frequency extraction (delegated to collection.keyword_suggest)
3. Run LLM keyword expansion (uses the same Groq endpoint as the judge)
4. Merge, dedupe, and store results in Redis
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from aimw.collection.keyword_suggest import (
    extract_frequency_keywords,
    store_suggestions,
)

_LOG = logging.getLogger("aimw.workers.keyword_suggest")


async def _llm_suggest_keywords(
    flagged_texts: list[str],
    existing_keywords: list[str],
) -> list[dict[str, Any]]:
    """Ask the LLM to generate effective search queries for finding similar scams."""
    from aimw.core.config import get_settings
    from aimw.db.repositories.usage import UsageRepository
    from aimw.reasoning.client import build_chat_client

    cfg = get_settings()
    if cfg.resolved_llm_api_key is None and cfg.llm_require_auth:
        return []

    sample = flagged_texts[:10]
    combined = "\n---\n".join(sample)
    existing_str = ", ".join(existing_keywords) if existing_keywords else "(none)"

    system = (
        "You are an OSINT analyst specializing in financial fraud detection "
        "across Telegram, YouTube, TikTok, and Instagram."
    )
    user_msg = (
        f"Below are texts from messages/videos flagged as HIGH-risk financial scams. "
        f"Analyze the common patterns, phrases, and tactics used.\n\n"
        f"Generate 10-15 effective SEARCH KEYWORDS that would find similar scam "
        f"content on social media platforms. Think about:\n"
        f"- Common scam phrases in English, Russian, Kazakh, Hindi\n"
        f"- Investment/gambling scam terminology\n"
        f"- Recruitment/referral scheme phrases\n"
        f"- Platform-specific terms scammers use\n\n"
        f"Already being searched: {existing_str}\n"
        f"Do NOT repeat these. Generate NEW, different search terms.\n\n"
        f"FLAGGED CONTENT:\n{combined}"
    )

    try:
        from aimw.db.session import get_sessionmaker

        client = build_chat_client(UsageRepository(get_sessionmaker()))
        raw = await client.complete_json(
            system=system,
            user=user_msg,
            schema_name="KeywordSuggestions",
            max_tokens=2048,
        )
        items = raw.get("keywords", raw if isinstance(raw, list) else [])
        if isinstance(items, dict):
            items = [items]
        return [
            {
                "keyword": item["keyword"],
                "source": "llm",
                "reason": item.get("reason", ""),
                "confidence": 0.9,
            }
            for item in items
            if isinstance(item, dict) and "keyword" in item
        ]
    except Exception as exc:
        _LOG.warning("llm_keyword_suggest_failed", extra={"error": str(exc)})
        return []


async def generate_suggestions(
    existing_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Full suggestion pipeline: read flagged content -> frequency + LLM -> store."""
    from sqlalchemy import text

    from aimw.db.session import get_sessionmaker

    sm = get_sessionmaker()

    flagged_texts: list[str] = []
    async with sm() as session:
        rows = await session.execute(
            text(
                "SELECT r.markdown FROM reports r "
                "JOIN evidence_packages p ON r.report_id = p.report_id "
                "WHERE p.risk_level IN ('HIGH', 'CRITICAL') "
                "ORDER BY p.processed_at DESC LIMIT 50"
            )
        )
        for row in rows:
            md = row[0]
            if md:
                flagged_texts.append(md)

    if not flagged_texts:
        _LOG.info("keyword_suggest_no_flagged_content")
        return []

    current_keywords = existing_keywords or []

    freq_suggestions = extract_frequency_keywords(flagged_texts)
    llm_suggestions = await _llm_suggest_keywords(flagged_texts, current_keywords)

    all_suggestions = llm_suggestions + freq_suggestions
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    lower_existing = {k.lower() for k in current_keywords}
    for s in all_suggestions:
        kw = s["keyword"].lower().strip()
        if kw not in seen and kw not in lower_existing:
            seen.add(kw)
            deduped.append(s)

    result = deduped[:20]
    store_suggestions(result, len(flagged_texts))
    _LOG.info("keyword_suggest_done", extra={"count": len(result)})
    return result


__all__ = ["generate_suggestions"]
