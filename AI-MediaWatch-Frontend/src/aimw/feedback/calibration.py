"""Band-threshold calibration — §14 of AI_MediaWatch_v4.md.

``nudge(band, delta)`` adjusts one threshold in ``config/level_thresholds.yaml``
within bounded constraints and writes an audit-log row. A per-session cap of
±0.03 absolute delta per band prevents runaway drift from a burst of analyst
dismissals without a model re-evaluation.

``reset()`` restores the hard-coded §6.3 defaults and audit-logs the reset.

All writes are atomic (temp-file + os.replace).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from aimw.feedback import audit

# Default §6.3 thresholds — the single source of truth for resets.
DEFAULTS: dict[str, float] = {
    "critical": 0.80,
    "high": 0.60,
    "medium": 0.35,
    "low": 0.10,
}

# Anchored to the package config dir (was CWD-relative; see scoring.engine).
_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "level_thresholds.yaml"

# Per-session accumulated delta per band. Reset at process start (module load).
_session_deltas: dict[str, float] = {}

# Per-session cap: no band may move more than this in total (absolute).
_SESSION_CAP = 0.03

# Minimum gap that must be maintained between adjacent bands.
_MIN_GAP = 0.05

# Ordered bands from lowest threshold to highest.
_BAND_ORDER = ["low", "medium", "high", "critical"]


class SessionCapExceeded(ValueError):
    """Raised when the per-session delta cap for a band would be exceeded."""


class BandGapViolation(ValueError):
    """Raised when a nudge would collapse the gap between adjacent bands."""


def load_thresholds() -> dict[str, float]:
    """Load current thresholds from YAML, falling back to defaults."""
    if _THRESHOLDS_PATH.exists():
        raw: dict[str, Any] = yaml.safe_load(_THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
        thresholds: dict[str, float] = {}
        for band in _BAND_ORDER:
            val = raw.get(band)
            try:
                thresholds[band] = float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                thresholds[band] = DEFAULTS[band]
        return thresholds
    return dict(DEFAULTS)


def _save_thresholds(thresholds: dict[str, float]) -> None:
    """Atomically write thresholds to YAML."""
    _THRESHOLDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_THRESHOLDS_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.dump(thresholds, fh, default_flow_style=False, sort_keys=True)
        os.replace(tmp, _THRESHOLDS_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def nudge(
    band: str,
    delta: float,
    *,
    dry_run: bool = False,
    user_id: str = "system",
) -> dict[str, float]:
    """Shift a band threshold by ``delta``, subject to all safety guards.

    Parameters
    ----------
    band:
        One of ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.
    delta:
        Signed change to apply (positive = raise threshold).
        Clamped to ``[-0.03, +0.03]`` per call before the session cap check.
    dry_run:
        If True, validate but do not write or audit-log.

    Returns
    -------
    dict[str, float]
        The *new* thresholds (whether written or simulated).

    Raises
    ------
    ValueError
        ``band`` not in ``["low", "medium", "high", "critical"]``.
    SessionCapExceeded
        Per-session delta cap for this band would be exceeded.
    BandGapViolation
        The resulting threshold would collapse the gap with an adjacent band.
    """
    if band not in _BAND_ORDER:
        raise ValueError(f"unknown band {band!r}; must be one of {_BAND_ORDER}")

    # Clamp single-call delta.
    clamped = max(-_SESSION_CAP, min(delta, _SESSION_CAP))

    # Per-session cap check.
    accumulated = _session_deltas.get(band, 0.0)
    if abs(accumulated + clamped) > _SESSION_CAP + 1e-9:
        raise SessionCapExceeded(
            f"session cap ±{_SESSION_CAP} for band {band!r} would be exceeded "
            f"(accumulated={accumulated:+.4f}, requested={clamped:+.4f})"
        )

    thresholds = load_thresholds()
    before = dict(thresholds)
    new_val = round(thresholds[band] + clamped, 6)

    # Gap guard: ensure we stay _MIN_GAP away from both neighbours.
    idx = _BAND_ORDER.index(band)
    if idx > 0:
        lower_band = _BAND_ORDER[idx - 1]
        if new_val - thresholds[lower_band] < _MIN_GAP:
            raise BandGapViolation(
                f"nudge would close gap between {band!r} ({new_val:.4f}) and "
                f"{lower_band!r} ({thresholds[lower_band]:.4f}) below {_MIN_GAP}"
            )
    if idx < len(_BAND_ORDER) - 1:
        upper_band = _BAND_ORDER[idx + 1]
        if thresholds[upper_band] - new_val < _MIN_GAP:
            raise BandGapViolation(
                f"nudge would close gap between {upper_band!r} ({thresholds[upper_band]:.4f}) "
                f"and {band!r} ({new_val:.4f}) below {_MIN_GAP}"
            )

    thresholds[band] = new_val

    # Revision (R1/R2): the single-source ceiling is derived from HIGH, so any
    # nudge must keep the joint threshold/ceiling invariants valid.
    from aimw.scoring.engine import validate_thresholds

    validate_thresholds(thresholds)

    if not dry_run:
        _save_thresholds(thresholds)
        _session_deltas[band] = accumulated + clamped
        audit.append(
            "calibration_nudge",
            before=before,
            after=dict(thresholds),
            user_id=user_id,
            extra={"band": band, "delta": clamped, "session_total": _session_deltas[band]},
        )

    return thresholds


def reset(*, user_id: str = "system") -> None:
    """Restore §6.3 default thresholds and clear the session delta counters.

    The reset is audit-logged; it is always permitted regardless of the
    per-session cap (an operator can always restore defaults).
    """
    before = load_thresholds()
    _save_thresholds(dict(DEFAULTS))
    _session_deltas.clear()
    audit.append(
        "calibration_reset",
        before=before,
        after=dict(DEFAULTS),
        user_id=user_id,
    )


def session_deltas() -> dict[str, float]:
    """Return a copy of the current per-session accumulated deltas (read-only)."""
    return dict(_session_deltas)
