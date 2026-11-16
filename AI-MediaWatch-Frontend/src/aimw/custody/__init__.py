"""Tamper-evident chain of custody for evidence packages.

Each evidence piece is hashed individually (SHA-256 of its canonical JSON).
The chain is built by hashing each piece's hash together with the previous
link's hash (Merkle-style append-only log). The final ``chain_root`` is the
tamper-evident commitment to the entire evidence set in order.

Verification: re-hash each piece from its raw fields, recompute the chain,
compare against the stored ``chain_root``. Any modification to any piece
breaks the chain.

This module is pure stdlib — no I/O, no async, no external dependencies.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from aimw.core.schema.evidence import EvidencePackage, EvidencePiece


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _piece_canonical(piece: EvidencePiece) -> str:
    """Stable canonical JSON for one evidence piece (no floating-point drift)."""
    d = {
        "source": piece.source,
        "polarity": piece.polarity,
        "indicator_type": piece.indicator_type,
        "strength": piece.strength,
        "raw_value": piece.raw_value,
        "timestamp": piece.timestamp,
        "regulation_ref": piece.regulation_ref,
    }
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _pkg_canonical(package: EvidencePackage) -> str:
    d = {
        "report_id": package.report_id,
        "video_id": package.video_id,
        "platform": package.platform,
        "url": package.url,
        "collected_at": package.collected_at.isoformat(),
    }
    return json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def seal(
    package: EvidencePackage,
    final_score: float,
    risk_level: str,
    verdict: str,
    confidence: float | None,
    regulations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Create a tamper-evident case file from one evidence package.

    Parameters
    ----------
    package:
        The evidence package to seal.
    final_score:
        The computed final risk score (0–1).
    risk_level:
        The computed risk level (CLEAN / LOW / MEDIUM / HIGH / CRITICAL).
    verdict:
        Analyst or LLM verdict string (e.g. "HIGH", "confirmed_fraud").
    confidence:
        Confidence in the verdict (0–1), or None.
    regulations:
        Dict mapping regulation_ref → statute dict (from regulations.yaml).

    Returns
    -------
    dict
        A JSON-serialisable case file with a ``chain_root`` that a verifier
        can reproduce from the raw ``evidence_chain`` entries.
    """
    piece_entries: list[dict[str, Any]] = []
    chain_hash = "0" * 64  # genesis hash

    for piece in package.evidence:
        canonical = _piece_canonical(piece)
        piece_hash = _sha256(canonical)
        chain_hash = _sha256(piece_hash + chain_hash)

        reg_cite: str | None = None
        if piece.regulation_ref and piece.regulation_ref in regulations:
            reg = regulations[piece.regulation_ref]
            reg_cite = f"{reg.get('short', '')} — {reg.get('title', '')}"

        piece_entries.append({
            "hash": piece_hash,
            "indicator_type": piece.indicator_type,
            "polarity": piece.polarity,
            "strength": piece.strength,
            "source": piece.source,
            "timestamp": piece.timestamp,
            "raw_value": piece.raw_value[:300],
            "regulation_ref": piece.regulation_ref,
            "regulation_cite": reg_cite,
        })

    pkg_hash = _sha256(_pkg_canonical(package))
    seal_root = _sha256(chain_hash + pkg_hash + verdict + str(round(final_score, 6)))

    # Collect fired statutes (deduplicated).
    statutes_fired: dict[str, dict[str, Any]] = {}
    for entry in piece_entries:
        ref = entry.get("regulation_ref")
        if ref and ref in regulations and ref not in statutes_fired:
            reg = regulations[ref]
            statutes_fired[ref] = {
                "id": ref,
                "short": reg.get("short", ""),
                "title": reg.get("title", ""),
                "article": (reg.get("article") or "").strip(),
                "jurisdiction": reg.get("jurisdiction", "KZ"),
            }

    return {
        "case_id": f"CASE-{package.report_id[:8].upper()}",
        "report_id": package.report_id,
        "video_id": package.video_id,
        "platform": package.platform,
        "url": package.url,
        "collected_at": package.collected_at.isoformat(),
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "risk_level": risk_level,
        "final_score": round(final_score, 4),
        "confidence": round(confidence, 3) if confidence is not None else None,
        "chain_root": seal_root,
        "package_hash": pkg_hash,
        "n_evidence_pieces": len(piece_entries),
        "evidence_chain": piece_entries,
        "statute_violations": list(statutes_fired.values()),
        "entities": {
            "crypto_wallets": list(package.entities.crypto_wallets),
            "telegram_handles": list(package.entities.telegram_handles),
            "telegram_links": list(package.entities.telegram_links),
            "phone_numbers": list(package.entities.phone_numbers),
            "referral_codes": list(package.entities.referral_codes),
            "websites": list(package.entities.websites),
        },
    }


def verify_chain(case_file: dict[str, Any]) -> tuple[bool, str]:
    """Verify the evidence chain in a sealed case file.

    Returns (ok, reason) where reason explains any failure.
    """
    chain_hash = "0" * 64
    for i, entry in enumerate(case_file.get("evidence_chain", [])):
        canonical = json.dumps({
            "source": entry["source"],
            "polarity": entry["polarity"],
            "indicator_type": entry["indicator_type"],
            "strength": entry["strength"],
            "raw_value": entry["raw_value"],
            "timestamp": entry["timestamp"],
            "regulation_ref": entry["regulation_ref"],
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        expected_hash = _sha256(canonical)
        if expected_hash != entry["hash"]:
            return False, f"piece {i} ({entry['indicator_type']}): hash mismatch"
        chain_hash = _sha256(expected_hash + chain_hash)

    pkg_fields = {
        "report_id": case_file["report_id"],
        "video_id": case_file["video_id"],
        "platform": case_file["platform"],
        "url": case_file["url"],
        "collected_at": case_file["collected_at"],
    }
    pkg_hash = _sha256(
        json.dumps(pkg_fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )
    if pkg_hash != case_file.get("package_hash"):
        return False, "package metadata hash mismatch"

    seal_root = _sha256(
        chain_hash
        + pkg_hash
        + case_file["verdict"]
        + str(round(case_file["final_score"], 6))
    )
    if seal_root != case_file.get("chain_root"):
        return False, "chain root mismatch — file may have been tampered"

    return True, "ok"


__all__ = ["seal", "verify_chain"]
