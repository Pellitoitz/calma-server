"""Distribution fitting, goodness of fit, industrial plausibility, ranking.

Principles (docs/distribution_fitting.md):
* A fit produces CANDIDATES. The best-ranked plausible one is a SUGGESTED_CANDIDATE, never "the" distribution:
  it is used only after an explicit engineer decision (decision.py).
* No "p > 0.05 = correct". p-values are reported as NOMINAL (parameters are estimated from the same data, so KS/CvM
  p-values are optimistic) and never decide anything on their own. STATISTICAL RANKING uses AIC (lowest AIC is NOT
  "the true distribution"); ΔAIC <= 2 is the usual interpretive heuristic for similar support, not a test.
* `loc`: the normal estimates its mean (loc = μ). Lognormal, exponential, gamma and weibull are fitted WITHOUT a shift
  (loc fixed at 0, support from 0) because the engine has no location parameter; a process with a hard minimum time
  (never below 40 s) is therefore approximated and plausibility shows the mass below the observed minimum.
* Uniform: observed min/max (MLE) or engineer bounds. Triangular: calculated bounds (formula below) or engineer bounds,
  mode by moments. Every parameter carries its source (parameter_sources).
* A normal truncated after fitting is FIT_THEN_TRUNCATE (parameters fitted without truncation); fitting a truncated
  distribution (TRUNCATED_DISTRIBUTION_FIT) is not implemented.
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
class NotApplicable(ValueError):
    """The family cannot represent these data under the declared constraints (reported, never hidden)."""


BOUND_SOURCES = ("ENGINEER_BOUNDS", "PROCESS_SPECIFICATION")


def _src(source: str, method: str, value: float | None = None) -> dict:
    return {"source": source, "method": method, **({"value": value} if value is not None else {})}


def _fit_family(name: str, a: np.ndarray, bounds: dict | None = None) -> tuple[Any, dict, int, str, dict]:
    """Return (frozen scipy dist, simforge params, k estimated params, method, parameter sources).

    Every parameter says where it comes from: ESTIMATED_FROM_DATA (with the estimator), CALCULATED_BOUNDS (formula),
    or the engineer's ENGINEER_BOUNDS / PROCESS_SPECIFICATION."""
    st = _stats()
    n = a.size
    mle0 = "MLE, loc fijado en 0 (modelo sin desplazamiento: soporte desde 0)"
    if name == "normal":
        mu, sd = st.norm.fit(a)  # loc = mu IS estimated (never forced to 0)
        return (st.norm(mu, sd), {"dist": "normal", "mean": float(mu), "std": float(sd)}, 2, "MLE (loc = μ estimada)",
                {"mean": _src("ESTIMATED_FROM_DATA", "MLE (media muestral)"), "std": _src("ESTIMATED_FROM_DATA", "MLE (ddof=0)")})
    if name == "lognormal":
        s, _, scale = st.lognorm.fit(a, floc=0)
        mean = scale * math.exp(s * s / 2)
        std = mean * math.sqrt(math.exp(s * s) - 1)
        return (st.lognorm(s, 0, scale), {"dist": "lognormal", "mean": float(mean), "std": float(std)}, 2, "MLE (loc=0)",
                {"mean": _src("ESTIMATED_FROM_DATA", mle0), "std": _src("ESTIMATED_FROM_DATA", mle0)})
    if name == "exponential":
        _, scale = st.expon.fit(a, floc=0)
        return (st.expon(0, scale), {"dist": "exponential", "mean": float(scale)}, 1, "MLE (loc=0)",
                {"mean": _src("ESTIMATED_FROM_DATA", mle0)})
    if name == "gamma":
        k, _, scale = st.gamma.fit(a, floc=0)
        return (st.gamma(k, 0, scale), {"dist": "gamma", "shape": float(k), "scale": float(scale)}, 2, "MLE (loc=0)",
                {"shape": _src("ESTIMATED_FROM_DATA", mle0), "scale": _src("ESTIMATED_FROM_DATA", mle0)})
    if name == "weibull":
        c, _, scale = st.weibull_min.fit(a, floc=0)
        return (st.weibull_min(c, 0, scale), {"dist": "weibull", "shape": float(c), "scale": float(scale)}, 2, "MLE (loc=0)",
                {"shape": _src("ESTIMATED_FROM_DATA", mle0), "scale": _src("ESTIMATED_FROM_DATA", mle0)})
    b = bounds or {}
    lo, hi = float(a.min()), float(a.max())
    if b.get("low") is not None and lo < b["low"] or b.get("high") is not None and hi > b["high"]:
        raise NotApplicable(f"hay observaciones fuera de los límites declarados ({b.get('source')}: "
                            f"[{b.get('low')}, {b.get('high')}]; observado [{lo:g}, {hi:g}]): revisa límites o datos")
    if name == "uniform":
        # MLE of U(a, b) = observed min and max. No hidden widening.
        low = float(b["low"]) if b.get("low") is not None else lo
        high = float(b["high"]) if b.get("high") is not None else hi
        src = {"low": _src(b["source"], "declarado", low) if b.get("low") is not None else _src("ESTIMATED_FROM_DATA", "OBSERVED_RANGE: mínimo observado (MLE)", low),
               "high": _src(b["source"], "declarado", high) if b.get("high") is not None else _src("ESTIMATED_FROM_DATA", "OBSERVED_RANGE: máximo observado (MLE)", high)}
        k = (b.get("low") is None) + (b.get("high") is None)
        return st.uniform(low, high - low), {"dist": "uniform", "low": low, "high": high}, k, "OBSERVED_RANGE / límites declarados", src
    if name == "triangular":
        # A triangular with low = observed min has ZERO density there (log-likelihood -inf), so data-based bounds are the
        # observed range widened by one mean spacing (max-min)/(n-1) on each side (CALCULATED_BOUNDS). This mirrors the
        # unbiased endpoint correction of a uniform; for a triangular it is a documented heuristic, not an MLE.
        sp = (hi - lo) / (n - 1) if n > 1 else 0.0
        src: dict = {}
        if b.get("low") is not None:
            low = float(b["low"])
            src["low"] = _src(b["source"], "declarado", low)
        else:
            low = lo - sp
            m = "CALCULATED_BOUNDS: mín − (máx − mín)/(n − 1)"
            if low < 0:
                low, m = 0.0, m + " → < 0, RECORTADO A 0 (explícito)"
            src["low"] = _src("CALCULATED_BOUNDS", m, low)
        if b.get("high") is not None:
            high = float(b["high"])
            src["high"] = _src(b["source"], "declarado", high)
        else:
            high = hi + sp
            src["high"] = _src("CALCULATED_BOUNDS", "CALCULATED_BOUNDS: máx + (máx − mín)/(n − 1)", high)
        raw_mode = 3 * float(a.mean()) - low - high
        mode = min(max(raw_mode, low), high)
        src["mode"] = _src("ESTIMATED_FROM_DATA", "momentos: 3·media − low − high" + (" → fuera de [low, high], RECORTADA" if mode != raw_mode else ""), mode)
        w = high - low
        k = 1 + (b.get("low") is None) + (b.get("high") is None)
        return (st.triang((mode - low) / w, low, w), {"dist": "triangular", "low": low, "mode": mode, "high": high}, k,
                "límites calculados/declarados, moda por momentos", src)
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
                   families: list[str] | None = None, notes: list[str] | None = None, bounds: dict | None = None) -> dict:
    """Fit all families + deterministic and empirical options. Returns a JSON-serialisable report."""
    from .stats import size_class
    st = _stats()
    a = np.sort(np.asarray(values, dtype=float))
    n = int(a.size)
    if bounds is not None and bounds.get("source") not in BOUND_SOURCES:
        raise ValueError(f"bounds['source'] debe ser uno de {BOUND_SOURCES}: los límites físicos no se inventan")
    report: dict[str, Any] = {"n": n, "unit": unit, "size_class": size_class(n), "notes": list(notes or []), "bounds": bounds,
                              "physical_min": physical_min, "physical_max": physical_max,
                              "options": {"DETERMINISTIC": {"MEAN": float(a.mean()) if n else None,
                                                            "MEDIAN": float(np.median(a)) if n else None},
                                          "EMPIRICAL": empirical_info(a)},
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
            d, params, k, method, sources = _fit_family(fam, a, bounds)
            ll = float(np.sum(d.logpdf(a)))
            if not math.isfinite(ll):
                raise ValueError("log-verosimilitud no finita (datos fuera del soporte)")
        except NotApplicable as e:
            c.update(status="NOT_APPLICABLE", reason=str(e))
            cands.append(c)
            continue
        except Exception as e:  # noqa: BLE001 - a family that cannot be fitted is reported, not hidden
            c.update(status="FIT_FAILED", reason=str(e)[:200])
            cands.append(c)
            continue
        ks = st.kstest(a, d.cdf)
        cvm = st.cramervonmises(a, d.cdf)
        c.update({"status": "OK", "method": method, "params": params, "parameter_sources": sources, "k": k, "loglik": ll, "aic": 2 * k - 2 * ll,
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
                                                           "pmin": physical_min, "pmax": physical_max, "b": bounds},
                                                          sort_keys=True).encode()).hexdigest()[:12]
    return report


def empirical_info(a) -> dict:
    """What an empirical distribution can and cannot generate. Small samples are a warning, never an automatic block."""
    a = np.asarray(a, dtype=float)
    n = int(a.size)
    from .stats import size_class
    info = {"sample_size": n, "n": n, "mean": float(a.mean()) if n else None,
            "observed_min": float(a.min()) if n else None, "observed_max": float(a.max()) if n else None,
            "distinct_values": int(np.unique(a).size) if n else 0, "support": "OBSERVED_VALUES_ONLY",
            "note": "re-muestrea SOLO valores observados: nunca genera valores fuera de [observed_min, observed_max] "
                    "ni valores intermedios no medidos (sin KDE ni extrapolación de colas)", "warnings": []}
    if n and size_class(n) in ("VERY_SMALL_SAMPLE", "SMALL_SAMPLE"):
        info["warnings"].append(f"EMPIRICAL_SMALL_SAMPLE: solo {n} valores distintos posibles como mucho; la cola real "
                                "(ciclos más largos que el máximo medido) no aparecerá en la simulación")
    return info


def candidate(report: dict, family: str) -> dict:
    for c in report["candidates"]:
        if c["family"] == family:
            return c
    raise KeyError(f"El ajuste {report.get('fit_id')} no tiene candidato '{family}'.")



def evaluate_holdout(train: list[float], test: list[float], unit: str, families: list[str] | None = None) -> dict:
    """Temporal holdout: fit on the first part, check against the later part that the fit never saw.

    The KS p-values here are NOT nominal-optimistic (parameters do not come from `test`), but they still assume
    independent observations. A train/test difference (two-sample KS) signals drift between periods."""
    st = _stats()
    tr = np.sort(np.asarray(train, dtype=float))
    te = np.asarray(test, dtype=float)
    out: dict[str, Any] = {"n_train": int(tr.size), "n_test": int(te.size), "unit": unit,
                           "test_observed": {"mean": float(te.mean()), "P50": float(np.percentile(te, 50)),
                                             "P95": float(np.percentile(te, 95)) if te.size >= 20 else None},
                           "candidates": []}
    two = st.ks_2samp(tr, te)
    out["train_vs_test"] = {"ks_stat": float(two.statistic), "p_value": float(two.pvalue),
                            "train_mean": float(tr.mean()), "test_mean": float(te.mean()),
                            "flag": "POSSIBLE_DRIFT" if two.pvalue < 0.01 else "NO_CLEAR_DRIFT",
                            "meaning": "la parte final no se parece a la inicial: el proceso pudo cambiar (aprendizaje, "
                                       "producto, método); ninguna distribución ajustada al principio la representará"
                            if two.pvalue < 0.01 else ""}
    for fam in families or FAMILIES:
        c: dict[str, Any] = {"family": fam}
        try:
            d, params, _, _, _ = _fit_family(fam, tr)
            ll = d.logpdf(te)
        except Exception as e:  # noqa: BLE001 - reported
            c.update(status="NOT_EVALUATED", reason=str(e)[:160])
            out["candidates"].append(c)
            continue
        ks = st.kstest(te, d.cdf)
        c.update(status="OK", params=params, test_ks_stat=float(ks.statistic), test_ks_p=float(ks.pvalue),
                 test_mean_loglik=float(np.mean(ll)) if np.all(np.isfinite(ll)) else None,
                 predicted={"mean": float(d.mean()), "P50": float(d.ppf(0.5)), "P95": float(d.ppf(0.95))})
        if c["test_mean_loglik"] is None:
            c["note"] = "valores de la parte final fuera del soporte ajustado (log-verosimilitud −∞)"
        out["candidates"].append(c)
    ok = [c for c in out["candidates"] if c.get("test_mean_loglik") is not None]
    for r, c in enumerate(sorted(ok, key=lambda c: -c["test_mean_loglik"]), start=1):
        c["holdout_rank"] = r
    emp_q = {"P50": float(np.percentile(tr, 50)), "P95": float(np.percentile(tr, 95)) if tr.size >= 20 else None}
    out["empirical_train"] = {"P50": emp_q["P50"], "P95": emp_q["P95"], "max": float(tr.max()),
                              "test_above_train_max": int(np.sum(te > tr.max())),
                              "note": "valores de la parte final por encima del máximo de ajuste: una empírica no los generaría"}
    return out
