"""Binary and per-class classification metrics for real-world validation.

Binary positive definition:
  - expected positive: expected_label in {"gambling", "pyramid", "scam"}
  - predicted positive: risk_level in {"HIGH", "CRITICAL"}
  - "uncertain" cases are excluded from binary metrics
"""
from __future__ import annotations

from dataclasses import dataclass

from aimw.validation.models import ValidationCase

_POSITIVE_LABELS = frozenset({"gambling", "pyramid", "scam"})
_POSITIVE_LEVELS = frozenset({"HIGH", "CRITICAL"})
_ALL_LEVELS = ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]


@dataclass
class BinaryMetrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def fpr(self) -> float:
        denom = self.fp + self.tn
        return self.fp / denom if denom > 0 else 0.0

    @property
    def fnr(self) -> float:
        denom = self.tp + self.fn
        return self.fn / denom if denom > 0 else 0.0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    def as_dict(self) -> dict[str, float]:
        return {
            "tp": float(self.tp),
            "fp": float(self.fp),
            "fn": float(self.fn),
            "tn": float(self.tn),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "fpr": self.fpr,
            "fnr": self.fnr,
        }


@dataclass
class EvaluationResult:
    binary: BinaryMetrics
    per_class: dict[str, dict[str, int]]
    confusion_matrix: dict[str, dict[str, int]]
    n_total: int
    n_evaluated: int
    n_skipped: int
    n_pending: int
    n_error: int

    def as_dict(self) -> dict[str, object]:
        return {
            "binary": self.binary.as_dict(),
            "per_class": self.per_class,
            "confusion_matrix": self.confusion_matrix,
            "n_total": self.n_total,
            "n_evaluated": self.n_evaluated,
            "n_skipped": self.n_skipped,
            "n_pending": self.n_pending,
            "n_error": self.n_error,
        }


def case_verdict(case: ValidationCase) -> str:
    """Return TP/FP/FN/TN/SKIP for a done case."""
    if case.processing_status != "done":
        return "SKIP"
    if case.expected_label == "uncertain":
        return "SKIP"
    predicted_positive = (case.risk_level or "UNKNOWN") in _POSITIVE_LEVELS
    expected_positive = case.expected_label in _POSITIVE_LABELS
    if expected_positive and predicted_positive:
        return "TP"
    if expected_positive and not predicted_positive:
        return "FN"
    if not expected_positive and predicted_positive:
        return "FP"
    return "TN"


def evaluate(cases: list[ValidationCase]) -> EvaluationResult:
    """Compute binary P/R/F1 and confusion matrix from all cases."""
    binary = BinaryMetrics()
    confusion: dict[str, dict[str, int]] = {}
    per_class: dict[str, dict[str, int]] = {}
    n_total = len(cases)
    n_pending = n_error = n_skipped = n_evaluated = 0

    for c in cases:
        if c.processing_status in ("pending", "running"):
            n_pending += 1
            continue
        if c.processing_status == "error":
            n_error += 1
            continue

        label = c.expected_label
        predicted_level = c.risk_level or "UNKNOWN"

        # Confusion matrix (expected_label → predicted_level bucket)
        confusion.setdefault(label, {})
        confusion[label][predicted_level] = confusion[label].get(predicted_level, 0) + 1

        if label == "uncertain":
            n_skipped += 1
            continue

        n_evaluated += 1
        ep = label in _POSITIVE_LABELS
        pp = predicted_level in _POSITIVE_LEVELS

        if ep and pp:
            binary.tp += 1
        elif ep and not pp:
            binary.fn += 1
        elif not ep and pp:
            binary.fp += 1
        else:
            binary.tn += 1

        per_class.setdefault(label, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if ep and pp:
            per_class[label]["tp"] += 1
        elif ep and not pp:
            per_class[label]["fn"] += 1
        elif not ep and pp:
            per_class[label]["fp"] += 1
        else:
            per_class[label]["tn"] += 1

    return EvaluationResult(
        binary=binary,
        per_class=per_class,
        confusion_matrix=confusion,
        n_total=n_total,
        n_evaluated=n_evaluated,
        n_skipped=n_skipped,
        n_pending=n_pending,
        n_error=n_error,
    )
