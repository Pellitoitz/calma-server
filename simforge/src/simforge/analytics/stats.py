"""Replication statistics (no scipy dependency)."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass

# two-sided 95% Student-t quantiles, df = 1..30
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def t95(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df <= 30:
        return _T95[df - 1]
    if df <= 60:
        return 2.042 - (df - 30) * (2.042 - 2.000) / 30
    if df <= 120:
        return 2.000 - (df - 60) * (2.000 - 1.980) / 60
    return 1.96


def percentile(values: list[float], q: float) -> float:
    """Linear interpolation percentile, q in [0, 100]."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class Stat:
    n: int
    mean: float
    std: float
    min: float
    max: float
    ci95_low: float
    ci95_high: float
    p50: float

    @property
    def half_width(self) -> float:
        return (self.ci95_high - self.ci95_low) / 2

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(values: list[float]) -> Stat:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    n = len(vals)
    if n == 0:
        nan = float("nan")
        return Stat(0, nan, nan, nan, nan, nan, nan, nan)
    mean = statistics.fmean(vals)
    std = statistics.stdev(vals) if n > 1 else 0.0
    hw = t95(n - 1) * std / math.sqrt(n) if n > 1 else float("nan")
    return Stat(n, mean, std, min(vals), max(vals), mean - hw if n > 1 else float("nan"),
                mean + hw if n > 1 else float("nan"), percentile(vals, 50))
