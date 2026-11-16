"""ValidationCase — the unit of real-world validation data.

One case represents a single media item that has been (or will be) run through
the full production pipeline, alongside the analyst's expected label.

Persistence: JSONL at ``data/validation/cases.jsonl``.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

_CASES_PATH = Path(__file__).resolve().parents[3] / "data" / "validation" / "cases.jsonl"

ExpectedLabel = Literal["benign", "gambling", "pyramid", "scam", "uncertain"]
ProcessingStatus = Literal["pending", "running", "done", "error"]


class ValidationCase(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str  # telegram | youtube | local | unknown
    source_url: str
    video_id: str
    expected_label: ExpectedLabel
    system_score: float | None = None
    risk_level: str | None = None  # CLEAN / LOW / MEDIUM / HIGH / CRITICAL
    action: str | None = None
    processing_status: ProcessingStatus = "pending"
    split: str | None = None  # "train" | "holdout" — for generalization reporting
    entity_count: dict[str, int] = Field(default_factory=dict)
    notes: str | None = None
    analyst_verdict: str | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None
    error_message: str | None = None


def load_cases(path: Path | None = None) -> list[ValidationCase]:
    """Read all cases from the JSONL file."""
    p = path or _CASES_PATH
    if not p.exists():
        return []
    cases: list[ValidationCase] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(Exception):
            cases.append(ValidationCase.model_validate(json.loads(line)))
    return cases


def save_cases(cases: list[ValidationCase], path: Path | None = None) -> None:
    """Atomically rewrite the JSONL file."""
    p = path or _CASES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for c in cases:
                fh.write(c.model_dump_json() + "\n")
        os.replace(tmp, p)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def append_case(case: ValidationCase, path: Path | None = None) -> None:
    """Append a single case to the JSONL file (creates dir if needed)."""
    p = path or _CASES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(case.model_dump_json() + "\n")


def update_case(updated: ValidationCase, path: Path | None = None) -> bool:
    """Replace the case with the matching case_id. Returns True if found."""
    cases = load_cases(path)
    for i, c in enumerate(cases):
        if c.case_id == updated.case_id:
            cases[i] = updated
            save_cases(cases, path)
            return True
    return False
