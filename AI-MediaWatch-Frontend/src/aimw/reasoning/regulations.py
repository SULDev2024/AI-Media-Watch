"""Kazakhstan regulatory statute catalog — in-memory loader.

Loads ``config/regulations_kz.yaml`` once (mtime-cached) and returns a
dict keyed by statute id so the custody module and report generator can
produce legally-grounded citations without calling an LLM.

Usage::

    regs = load()
    statute = regs.get("art_7_gambling_kz")
    if statute:
        print(statute["short"])   # "ЗРК об азартных играх, ст. 7"
        print(statute["title"])   # "Незаконная организация и реклама азартных игр"
        print(statute["article"]) # full article text
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path("config/regulations_kz.yaml")

_cache: dict[str, dict[str, Any]] | None = None
_mtime: float = -1.0


def load() -> dict[str, dict[str, Any]]:
    """Return the statute catalog (hot-reloaded when the file changes)."""
    global _cache, _mtime

    try:
        mtime = os.path.getmtime(_YAML_PATH)
    except OSError:
        return {}

    if _cache is not None and mtime == _mtime:
        return _cache

    try:
        raw: Any = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
        statutes: list[dict[str, Any]] = raw.get("statutes", [])
        _cache = {s["id"]: s for s in statutes if "id" in s}
    except Exception:
        _cache = {}

    _mtime = mtime
    return _cache


def cite(regulation_ref: str | None) -> str | None:
    """Return a one-line citation for a regulation_ref, or None if not found."""
    if not regulation_ref:
        return None
    reg = load().get(regulation_ref)
    if not reg:
        return None
    return f"{reg.get('short', regulation_ref)} — {reg.get('title', '')}"


__all__ = ["load", "cite"]
