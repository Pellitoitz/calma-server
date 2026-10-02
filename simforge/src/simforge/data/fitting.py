"""Distribution fitting, goodness of fit, industrial plausibility, ranking.

Principles (docs/distribution_fitting.md):
* A fit produces CANDIDATES. The best-ranked plausible one is a SUGGESTED_CANDIDATE, never "the" distribution:
  it is used only after an explicit engineer decision (decision.py).
* No "p > 0.05 = correct". p-values are reported as NOMINAL (parameters are estimated from the same data, so KS/CvM
  p-values are optimistic) and never decide anything on their own. Ranking uses AIC; ΔAIC <= 2 = practically equivalent.
* All engine families have support starting at 0 (no location/shift parameter): fits use loc = 0. A process with a hard
  minimum time (e.g. never below 40 s) is therefore approximated; plausibility shows how much mass falls below the
  observed minimum.
* Industrial plausibility (P1/P50/P95/P99/P99.9, support, tail extrapolation, mean preservation) is part of the result,
  because two families with the same AIC can generate very different long cycles.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

FAMILIES = ["normal", "lognormal", "exponential", "gamma", "weibull", "triangular", "uniform"]
QUANTILES = {"P1": 0.01, "P50": 0.50, "P95": 0.95, "P99": 0.99, "P99.9": 0.999}
EQUIVALENT_DAIC = 2.0
MEAN_TOL_WARN, MEAN_TOL_CRIT = 0.02, 0.10
TAIL_RATIO_WARN = 1.5  # fitted P99.9 / observed max
NEG_MASS_LIMIT = 1e-9  # same limit as the engine's Normal validator


def _stats():
    from scipy import stats
    return stats


# ------------------------------------------------------------------------------------------- families
def _fit_family(name: str, a: np.ndarray) -> tuple[Any, dict, int, str]:
    """Return (frozen scipy dist, simforge params, k, method)."""
    st = _stats()
    n = a.size
    if name == "normal":
        mu, sd = st.norm.fit(a)
        return st.norm(mu, sd), {"dist": "normal", "mean": float(mu), "std": float(sd)}, 2, "MLE"
    if name == "lognormal":
        s, _, scale = st.lognorm.fit(a, floc=0)
        mean = scale * math.exp(s * s / 2)
        std = mean * math.sqrt(math.exp(s * s) - 1)
        return st.lognorm(s, 0, scale), {"dist": "lognormal", "mean": float(mean), "std": float(std)}, 2, "MLE (loc=0)"
    if name == "exponential":
        _, scale = st.expon.fit(a, floc=0)
        return st.expon(0, scale), {"dist": "exponential", "mean": float(scale)}, 1, "MLE (loc=0)"
    if name == "gamma":
        k, _, scale = st.gamma.fit(a, floc=0)
        return st.gamma(k, 0, scale), {"dist": "gamma", "shape": float(k), "scale": float(scale)}, 2, "MLE (loc=0)"
    if name == "weibull":
        c, _, scale = st.weibull_min.fit(a, floc=0)
        return st.weibull_min(c, 0, scale), {"dist": "weibull", "shape": float(c), "scale": float(scale)}, 2, "MLE (loc=0)"
    lo, hi = float(a.min()), float(a.max())
    pad = (hi - lo) / (n - 1) if n > 1 else 0.0  # unbiased-type extension of the observed range
    low, high = max(0.0, lo - pad), hi + pad
    if name == "uniform":
        return st.uniform(low, high - low), {"dist": "uniform", "low": low, "high": high}, 2, "range ± (max−min)/(n−1)"
    if name == "triangular":
        mode = min(max(3 * float(a.mean()) - low - high, low), high)
        w = high - low
        return (st.triang((mode - low) / w, low, w), {"dist": "triangular", "low": low, "mode": mode, "high": high}, 3,
                "range ± (max−min)/(n−1), mode by moments")
    raise ValueError(name)


def _ad_statistic(a_sorted: np.ndarray, cdf) -> float:
    n = a_sorted.size
    f = np.clip(cdf(a_sorted), 1e-12, 1 - 1e-12)
    i = np.arange(1, n + 1)
    return float(-n - np.sum((2 * i - 1) * (np.log(f) + np.log(1 - f[::-1]))) / n)


def _plausibility(d, a: np.ndarray, params: dict, physical_min: float | None, physical_max: float | None) -> dict:
    n = a.size
    obs_q = {k: (float(np.percentile(a, q * 100)) if (q * n >= 1 and (1 - q) * n >= 1) else None) for k, q in QUANTILES.items()}
    fit_q = {k: float(d.ppf(q)) for k, q in QUANTILES.items()}
    lo_support = float(d.support()[0])
    flags: list[dict] = []

    def flag(sev: str, code: str, text: str) -> None:
        flags.append({"severity": sev, "code": code, "text": text})

    p_neg = float(d.cdf(0.0))
    if p_neg > NEG_MASS_LIMIT:
        flag("CRITICAL", "NEGATIVE_SUPPORT", f"P(t < 0) = {p_neg:.2g}: genera tiempos negativos; solo usable con truncamiento explícito")
    mean_obs = float(a.mean())
    rel = abs(float(d.mean()) - mean_obs) / mean_obs if mean_obs else 0.0
    if rel > MEAN_TOL_CRIT:
        flag("CRITICAL", "MEAN_MISMATCH", f"media ajustada difiere {rel:.1%} de la observada (afecta directamente al throughput)")
    elif rel > MEAN_TOL_WARN:
        flag("WARNING", "MEAN_MISMATCH", f"media ajustada difiere {rel:.1%} de la observada")
    mx, mn = float(a.max()), float(a.min())
    ratio = fit_q["P99.9"] / mx if mx > 0 else None
    if ratio is not None and ratio > TAIL_RATIO_WARN:
        flag("WARNING", "TAIL_EXTRAPOLATION", f"P99.9 ajustado = {fit_q['P99.9']:.4g} es {ratio:.1f}× el máximo observado ({mx:.4g}): "
                                              "la cola genera ciclos más largos que ninguno medido")
    p_above_3max = float(d.sf(3 * mx))
    if p_above_3max > 1e-4:
        flag("WARNING", "EXTREME_TAIL", f"P(t > 3·máx observado) = {p_above_3max:.2g}")
    p_below_min = float(d.cdf(mn))
    if p_below_min > max(0.05, 3.0 / n):
        flag("WARNING", "MASS_BELOW_OBSERVED_MIN", f"{p_below_min:.1%} de las muestras serían menores que el mínimo observado ({mn:.4g})")
    if float(d.sf(mx)) == 0.0:
        flag("INFO", "BOUNDED_SUPPORT", f"nunca genera valores > {float(d.support()[1]):.4g} (rango observado ampliado)")
    phys = {}
    if physical_min is not None:
        phys["p_below_physical_min"] = float(d.cdf(physical_min))
        if phys["p_below_physical_min"] > 0.001:
            flag("WARNING", "BELOW_PHYSICAL_MIN", f"P(t < mínimo físico {physical_min:g}) = {phys['p_below_physical_min']:.2%}")
    if physical_max is not None:
        phys["p_above_physical_max"] = float(d.sf(physical_max))
        if phys["p_above_physical_max"] > 0.001:
            flag("WARNING", "ABOVE_PHYSICAL_MAX", f"P(t > máximo físico {physical_max:g}) = {phys['p_above_physical_max']:.2%}")
    return {"observed_quantiles": obs_q, "fitted_quantiles": fit_q, "support_lower": lo_support,
            "support_upper": float(d.support()[1]), "p_negative": p_neg, "fitted_mean": float(d.mean()),
            "fitted_std": float(d.std()), "observed_mean": mean_obs, "p_below_observed_min": p_below_min,
            "tail_ratio_p999_over_max": ratio, **phys, "flags": flags}


def _qq(d, a_sorted: np.ndarray) -> dict:
    n = a_sorted.size
    pp = (np.arange(1, n + 1) - 0.5) / n
    th = d.ppf(pp)
    corr = float(np.corrcoef(th, a_sorted)[0, 1]) if n > 2 and np.std(a_sorted) > 0 else None
    top = max(1, n // 10)
    rel_tail = float(np.max(np.abs(th[-top:] - a_sorted[-top:]) / np.maximum(a_sorted[-top:], 1e-12)))
    return {"theoretical": th.tolist(), "observed": a_sorted.tolist(), "correlation": corr, "max_rel_dev_top10pct": rel_tail}


def fit_candidates(values: list[float], unit: str, physical_min: float | None = None, physical_max: float | None = None,
                   families: list[str] | None = None, notes: list[str] | None = None) -> dict:
    """Fit all families + deterministic and empirical options. Returns a JSON-serialisable report."""
    from .stats import size_class
    st = _stats()
    a = np.sort(np.asarray(values, dtype=float))
    n = int(a.size)
    report: dict[str, Any] = {"n": n, "unit": unit, "size_class": size_class(n), "notes": list(notes or []),
                              "physical_min": physical_min, "physical_max": physical_max,
                              "options": {"DETERMINISTIC": {"MEAN": float(a.mean()) if n else None,
                                                            "MEDIAN": float(np.median(a)) if n else None},
                                          "EMPIRICAL": {"n": n, "mean": float(a.mean()) if n else None,
                                                        "note": "re-muestrea SOLO valores observados: no genera nada fuera del "
                                                                "rango medido (ni más corto ni más largo)"}},
                              "candidates": [], "suggested": None}
    from .stats import MIN_FIT_N
    if n < MIN_FIT_N:
        report["notes"].append(f"n = {n} < {MIN_FIT_N}: no se ajustan distribuciones (ajuste degenerado). Opciones: determinista "
                               "(media/mediana/valor del ingeniero) o empírica. Recomendación: medir más.")
        return report
    if np.ptp(a) == 0:
        report["notes"].append("todos los valores son iguales: solo tiene sentido un valor determinista")
        return report
    if n < 10:
        report["notes"].append("VERY_SMALL_SAMPLE: n < 10; el ajuste se muestra pero está muy poco informado. Usarlo exige "
                               "aceptarlo explícitamente (VERY_SMALL_SAMPLE)")
    elif n < 30:
        report["notes"].append("SMALL_SAMPLE: con n < 30 los tests apenas discriminan entre familias; la elección se basa sobre todo "
                               "en plausibilidad industrial y conocimiento del proceso")
    if len(np.unique(a)) < n / 2:
        report["notes"].append(f"TIES: solo {len(np.unique(a))} valores distintos en {n}: datos redondeados; KS/AD/CvM sesgados")
    cands = []
    for fam in families or FAMILIES:
        c: dict[str, Any] = {"family": fam}
        if fam in ("lognormal", "gamma", "weibull") and a.min() <= 0:
            c.update(status="NOT_APPLICABLE", reason="la familia exige t > 0 y hay valores = 0")
            cands.append(c)
            continue
        try:
            d, params, k, method = _fit_family(fam, a)
            ll = float(np.sum(d.logpdf(a)))
            if not math.isfinite(ll):
                raise ValueError("log-verosimilitud no finita (datos fuera del soporte)")
        except Exception as e:  # noqa: BLE001 - a family that cannot be fitted is reported, not hidden
            c.update(status="FIT_FAILED", reason=str(e)[:200])
            cands.append(c)
            continue
        ks = st.kstest(a, d.cdf)
        cvm = st.cramervonmises(a, d.cdf)
        c.update({"status": "OK", "method": method, "params": params, "k": k, "loglik": ll, "aic": 2 * k - 2 * ll,
                  "bic": k * math.log(n) - 2 * ll,
                  "gof": {"ks_stat": float(ks.statistic), "ks_p_nominal": float(ks.pvalue), "ad_stat": _ad_statistic(a, d.cdf),
                          "cvm_stat": float(cvm.statistic), "cvm_p_nominal": float(cvm.pvalue),
                          "p_values_note": "nominales: parámetros estimados con los mismos datos -> optimistas; no deciden nada"},
                  "qq": _qq(d, a), "plausibility": _plausibility(d, a, params, physical_min, physical_max)})
        if fam == "normal" and c["plausibility"]["p_negative"] > NEG_MASS_LIMIT:
            c["status"] = "REQUIRES_TRUNCATION"
            c["reason"] = "masa negativa no despreciable: solo aplicable con truncamiento explícito aceptado por el ingeniero"
        cands.append(c)
    ok = [c for c in cands if c.get("aic") is not None]
    if ok:
        best = min(c["aic"] for c in ok)
        for c in ok:
            c["delta_aic"] = c["aic"] - best
            c["practically_equivalent_to_best"] = c["delta_aic"] <= EQUIVALENT_DAIC
        ok.sort(key=lambda c: c["aic"])
        for r, c in enumerate(ok, start=1):
            c["rank"] = r
    report["candidates"] = ok + [c for c in cands if c.get("aic") is None]
    eligible = [c for c in ok if c["status"] == "OK" and not any(f["severity"] == "CRITICAL" for f in c["plausibility"]["flags"])]
    if eligible:
        s = eligible[0]
        report["suggested"] = {"family": s["family"], "status": "SUGGESTED_CANDIDATE - REQUIRES ENGINEER ACCEPTANCE",
                               "why": f"menor AIC entre candidatos sin problemas CRÍTICOS de plausibilidad (ΔAIC = {s['delta_aic']:.2f})",
                               "equivalent_alternatives": [c["family"] for c in eligible[1:] if c["practically_equivalent_to_best"]]}
    if ok and all(c["gof"]["ks_p_nominal"] < 0.01 for c in ok):
        report["notes"].append("NINGUNA familia paramétrica reproduce bien los datos (KS nominal < 0.01 en todas): considera la "
                               "distribución EMPÍRICA, o revisa si hay grupos mezclados / dependencia serial")
    report["fit_id"] = "fit_" + hashlib.sha256(json.dumps({"x": a.tolist(), "u": unit, "f": families or FAMILIES,
                                                           "pmin": physical_min, "pmax": physical_max}).encode()).hexdigest()[:12]
    return report


def candidate(report: dict, family: str) -> dict:
    for c in report["candidates"]:
        if c["family"] == family:
            return c
    raise KeyError(f"El ajuste {report.get('fit_id')} no tiene candidato '{family}'.")

