"""Descriptive statistics, plot data, sample-size class, serial dependence, bootstrap, group heterogeneity.

Everything is computed on the rows USED (VALID/WARNING/accepted, not excluded) and states n.
Requires numpy (+ scipy for skewness/kurtosis/Kruskal-Wallis): pip install 'simforge[data]'.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Sample-size classes (documented in docs/distribution_fitting.md). They are WARNINGS, not laws: they never block the
# analysis; they are shown next to every result and VERY_SMALL_SAMPLE must be accepted explicitly before USE_FITTED.
#   VERY_SMALL_SAMPLE   n < 10    a fit is shown (n >= 5) but is barely informed; prefer DETERMINISTIC/EMPIRICAL, measure more
#   SMALL_SAMPLE        10..29    GOF tests have very low power: several families "pass"; decide on process knowledge
#   USABLE_WITH_CAUTION 30..99    fit meaningful for the body; tails (P99+) are extrapolation
#   LARGER_SAMPLE       >= 100    fit and GOF informative; P99.9 still extrapolated unless n is in the thousands
SIZE_LIMITS = [(10, "VERY_SMALL_SAMPLE"), (30, "SMALL_SAMPLE"), (100, "USABLE_WITH_CAUTION")]
SIZE_TEXT = {
    "VERY_SMALL_SAMPLE": "n < 10: evidencia muy débil; preferir valor determinista o empírico, y medir más",
    "SMALL_SAMPLE": "10 <= n < 30: los tests de bondad de ajuste apenas discriminan; varias familias 'pasan'",
    "USABLE_WITH_CAUTION": "30 <= n < 100: ajuste útil para el cuerpo; colas (P99+) extrapoladas",
    "LARGER_SAMPLE": "n >= 100: ajuste y bondad de ajuste informativos; P99.9 sigue siendo extrapolación salvo n muy grande",
}
MIN_FIT_N = 5  # below this a 2-parameter fit is degenerate: not computed
SERIAL_THRESHOLD_Z = 2.0  # |r1| > 2/sqrt(n) -> POSSIBLE_SERIAL_DEPENDENCE


def size_class(n: int) -> str:
    for lim, name in SIZE_LIMITS:
        if n < lim:
            return name
    return "LARGER_SAMPLE"


def describe(x: list[float] | np.ndarray, n_missing: int = 0, n_excluded: int = 0) -> dict[str, Any]:
    a = np.asarray(x, dtype=float)
    n = int(a.size)
    out: dict[str, Any] = {"n": n, "n_missing_or_invalid": n_missing, "n_excluded": n_excluded, "size_class": size_class(n),
                           "size_class_meaning": SIZE_TEXT[size_class(n)]}
    if n == 0:
        return out
    levels = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    q = np.percentile(a, levels)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if n > 1 else 0.0
    out.update({
        "mean": mean, "median": float(q[4]), "std": std, "variance": std ** 2, "min": float(a.min()), "max": float(a.max()),
        "range": float(a.max() - a.min()),
        # a percentile is reported only if at least one observation lies beyond it on each side (else it is extrapolated)
        **{f"p{lv}": (float(qv) if n * min(lv, 100 - lv) / 100 >= 1 else None) for lv, qv in zip(levels, q)},
        "q1": float(q[3]) if n >= 4 else None, "q3": float(q[5]) if n >= 4 else None,
        "iqr": float(q[5] - q[3]) if n >= 4 else None,
        "cv": std / mean if mean else None,
        "distinct_values": int(np.unique(a).size),
    })
    if n > 2 and std > 0:
        from scipy import stats as st
        out["skewness"] = float(st.skew(a, bias=False))
        out["kurtosis_excess"] = float(st.kurtosis(a, bias=False)) if n > 3 else None
    else:
        out["skewness"] = out["kurtosis_excess"] = None
    if n >= 2:
        se = std / math.sqrt(n)
        from scipy import stats as st
        t = float(st.t.ppf(0.975, n - 1))
        out["mean_ci95"] = [mean - t * se, mean + t * se]
    return out


def lag1(x: list[float] | np.ndarray) -> dict[str, Any]:
    """Lag-1 autocorrelation in the given ORDER (time order if a timestamp exists, else file order)."""
    a = np.asarray(x, dtype=float)
    n = a.size
    if n < 10 or a.std() == 0:
        return {"lag1": None, "n": int(n), "flag": "NOT_EVALUATED (n < 10 o varianza nula)"}
    d = a - a.mean()
    r1 = float(np.sum(d[1:] * d[:-1]) / np.sum(d * d))
    limit = SERIAL_THRESHOLD_Z / math.sqrt(n)
    flag = "POSSIBLE_SERIAL_DEPENDENCE" if abs(r1) > limit else "NO_EVIDENCE_OF_SERIAL_DEPENDENCE"
    return {"lag1": r1, "n": int(n), "limit": limit, "flag": flag,
            "meaning": ("las observaciones consecutivas están correlacionadas (aprendizaje, desgaste, lotes, turnos...). "
                        "Una distribución i.i.d. (la que usa el motor) no reproduce esa dependencia"
                        if flag == "POSSIBLE_SERIAL_DEPENDENCE" else "")}


def trend(x: list[float] | np.ndarray) -> dict[str, Any]:
    a = np.asarray(x, dtype=float)
    if a.size < 10:
        return {"flag": "NOT_EVALUATED"}
    from scipy import stats as st
    r = st.spearmanr(np.arange(a.size), a)
    rho, p = float(r.statistic), float(r.pvalue)
    return {"spearman_rho": rho, "p_value": p, "flag": "POSSIBLE_TREND" if p < 0.01 and abs(rho) > 0.2 else "NO_CLEAR_TREND"}


def bootstrap(x: list[float] | np.ndarray, seed: int = 12345, n_boot: int = 2000) -> dict[str, Any]:
    """Percentile bootstrap CIs (95 %) of mean, median, P95. Reproducible with `seed`. Only for n >= 10."""
    a = np.asarray(x, dtype=float)
    if a.size < 10:
        return {"evaluated": False, "reason": "n < 10: el bootstrap no es fiable con tan pocos datos"}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    s = a[idx]
    res = {"evaluated": True, "seed": seed, "n_boot": n_boot}
    for name, vals in (("mean", s.mean(axis=1)), ("median", np.median(s, axis=1)), ("p95", np.percentile(s, 95, axis=1))):
        lo, hi = np.percentile(vals, [2.5, 97.5])
        res[name] = [float(lo), float(hi)]
    res["note"] = "IC del P95 con n pequeño es amplio: la cola está poco informada"
    return res


def histogram(x: list[float] | np.ndarray) -> dict[str, Any]:
    a = np.asarray(x, dtype=float)
    if a.size == 0:
        return {"edges": [], "counts": []}
    counts, edges = np.histogram(a, bins="fd" if a.size >= 4 and np.ptp(a) > 0 else 1)
    if counts.size > 60:  # FD can explode on heavy tails
        counts, edges = np.histogram(a, bins=60)
    return {"edges": edges.tolist(), "counts": counts.tolist(), "rule": "Freedman-Diaconis (máx. 60 clases)"}


def ecdf(x: list[float] | np.ndarray) -> dict[str, list[float]]:
    a = np.sort(np.asarray(x, dtype=float))
    return {"x": a.tolist(), "p": (np.arange(1, a.size + 1) / a.size).tolist()}


def boxplot(x: list[float] | np.ndarray) -> dict[str, Any]:
    a = np.asarray(x, dtype=float)
    if a.size == 0:
        return {}
    q1, med, q3 = np.percentile(a, [25, 50, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = a[(a >= lo) & (a <= hi)]
    return {"q1": float(q1), "median": float(med), "q3": float(q3), "whisker_low": float(inside.min()), "whisker_high": float(inside.max()),
            "outside": a[(a < lo) | (a > hi)].tolist()}


def sequence(x: list[float], order: list[str | None] | None = None) -> dict[str, list]:
    return {"i": list(range(len(x))), "value": list(map(float, x)), "timestamp": order or [None] * len(x)}


def plot_data(x: list[float], timestamps: list[str | None] | None = None) -> dict[str, Any]:
    return {"histogram": histogram(x), "ecdf": ecdf(x), "boxplot": boxplot(x), "sequence": sequence(x, timestamps)}


def group_comparison(groups: dict[str, list[float]]) -> dict[str, Any]:
    """Per-group summary + Kruskal-Wallis as INFORMATION. Groups are never merged by this function."""
    rows = []
    for g, v in sorted(groups.items()):
        a = np.asarray(v, dtype=float)
        rows.append({"group": g, "n": int(a.size), "mean": float(a.mean()) if a.size else None,
                     "median": float(np.median(a)) if a.size else None,
                     "std": float(a.std(ddof=1)) if a.size > 1 else None})
    out: dict[str, Any] = {"groups": rows}
    valid = [np.asarray(v, dtype=float) for v in groups.values() if len(v) >= 5]
    if len(valid) >= 2:
        from scipy import stats as st
        r = st.kruskal(*valid)
        means = [float(v.mean()) for v in valid]
        out["kruskal_wallis_p"] = float(r.pvalue)
        out["max_mean_ratio"] = max(means) / min(means) if min(means) > 0 else None
        out["flag"] = ("GROUPS_DIFFER" if r.pvalue < 0.01 else "NO_CLEAR_DIFFERENCE")
        out["meaning"] = ("los grupos parecen tener distribuciones distintas: ajustar por grupo, o decidir explícitamente "
                          "mezclarlos (pooled) y documentarlo" if out["flag"] == "GROUPS_DIFFER" else
                          "no hay evidencia fuerte de diferencia; mezclar sigue siendo una decisión del ingeniero")
    else:
        out["flag"] = "NOT_EVALUATED (menos de 2 grupos con n >= 5)"
    return out
