"""Statistics for judge calibration, paired evaluation, and pass@k metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence

POS = "FAIL"  # the judge's job is to FIND failures, so FAIL is the positive class


def _paired_labels(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")
    h = [str(value).strip().upper() for value in human]
    j = [str(value).strip().upper() for value in judge]
    if any(value not in {"PASS", "FAIL"} for value in (*h, *j)):
        raise ValueError("labels must be PASS or FAIL")
    return h, j


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """Return tp/fp/fn/tn with FAIL as the positive class."""
    h, j = _paired_labels(human, judge)
    return {
        "tp": sum(a == POS and b == POS for a, b in zip(h, j)),
        "fp": sum(a != POS and b == POS for a, b in zip(h, j)),
        "fn": sum(a == POS and b != POS for a, b in zip(h, j)),
        "tn": sum(a != POS and b != POS for a, b in zip(h, j)),
    }


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    precision_den = cm["tp"] + cm["fp"]
    recall_den = cm["tp"] + cm["fn"]
    return (
        cm["tp"] / precision_den if precision_den else 0.0,
        cm["tp"] / recall_den if recall_den else 0.0,
    )


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """Cohen's kappa; undefined when expected agreement is exactly one."""
    h, j = _paired_labels(human, judge)
    n = len(h)
    if n == 0:
        raise ValueError("kappa is undefined for empty labels")
    h_pos = sum(value == POS for value in h) / n
    j_pos = sum(value == POS for value in j) / n
    observed = sum(a == b for a, b in zip(h, j)) / n
    expected = h_pos * j_pos + (1 - h_pos) * (1 - j_pos)
    if math.isclose(expected, 1.0, rel_tol=0.0, abs_tol=0.0):
        raise ValueError("kappa is undefined when expected agreement is one")
    return (observed - expected) / (1 - expected)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error and clip to [0, 1]."""
    values = (observed_rate, sensitivity, specificity)
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("rates must be finite values between 0 and 1")
    denominator = sensitivity + specificity - 1
    if denominator == 0:
        raise ValueError("Rogan-Gladen correction is undefined when sensitivity + specificity = 1")
    corrected = (observed_rate + specificity - 1) / denominator
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """Return paired percentile-bootstrap CI for mean(a) - mean(b)."""
    import numpy as np
    from scipy.stats import bootstrap

    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if len(a) == 0:
        raise ValueError("paired samples must not be empty")
    if not isinstance(n_resamples, int) or isinstance(n_resamples, bool) or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    if not np.all(np.isfinite(av)) or not np.all(np.isfinite(bv)):
        raise ValueError("paired samples must contain only finite values")
    difference = float(np.mean(av) - np.mean(bv))
    if np.array_equal(av, bv):
        return 0.0, 0.0, 0.0
    if len(av) == 1:
        # A one-item paired bootstrap always resamples that same item.
        return difference, difference, difference

    def mean_difference(x, y, axis=-1):
        return np.mean(x - y, axis=axis)

    result = bootstrap(
        (av, bv),
        mean_difference,
        paired=True,
        vectorized=True,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    return difference, float(result.confidence_interval.low), float(result.confidence_interval.high)


def _pass_k_args(n: int, c: int, k: int) -> None:
    if any(not isinstance(value, int) or isinstance(value, bool) for value in (n, c, k)):
        raise ValueError("n, c, and k must be integers")
    if n <= 0 or not 0 <= c <= n or not 1 <= k <= n:
        raise ValueError("require n > 0, 0 <= c <= n, and 1 <= k <= n")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased probability that at least one of k draws passes."""
    _pass_k_args(n, c, k)
    failures = n - c
    if failures < k:
        return 1.0
    return 1.0 - math.comb(failures, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Unbiased probability that all k draws pass (pass^k)."""
    _pass_k_args(n, c, k)
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)
