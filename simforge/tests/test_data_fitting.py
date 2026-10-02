"""Statistics and distribution fitting. Golden tests use known synthetic distributions, fixed seeds and tolerances;
they check that parameters are RECOVERED, never that a given family must win."""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from simforge.data import fitting, outliers, stats  # noqa: E402
from simforge.data.fitting import candidate, fit_candidates  # noqa: E402
from simforge.domain.values import Duration  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

RNG = np.random.default_rng(424242)
N = 2000


def _params(rep, fam):
    c = candidate(rep, fam)
    assert c["status"] in ("OK", "REQUIRES_TRUNCATION"), c
    return c["params"]


@pytest.mark.parametrize("fam,sample,check", [
    ("normal", lambda: RNG.normal(100, 10, N), lambda p: (p["mean"], p["std"], 100, 10)),
    ("lognormal", lambda: RNG.lognormal(math.log(40) - 0.5 * math.log(1 + 0.25 ** 2), math.sqrt(math.log(1 + 0.25 ** 2)), N),
     lambda p: (p["mean"], p["std"], 40, 10)),
    ("exponential", lambda: RNG.exponential(90, N), lambda p: (p["mean"], p["mean"], 90, 90)),
    ("gamma", lambda: RNG.gamma(4, 7.5, N), lambda p: (p["shape"], p["scale"], 4, 7.5)),
    ("weibull", lambda: 50 * RNG.weibull(2.2, N), lambda p: (p["shape"], p["scale"], 2.2, 50)),
    ("uniform", lambda: RNG.uniform(20, 30, N), lambda p: (p["low"], p["high"], 20, 30)),
    ("triangular", lambda: RNG.triangular(10, 14, 30, N), lambda p: (p["low"], p["high"], 10, 30)),
])
def test_fitting_recovers_known_parameters(fam, sample, check):
    rep = fit_candidates(sample().tolist(), "s")
    a, b, ta, tb = check(_params(rep, fam))
    assert a == pytest.approx(ta, rel=0.06) and b == pytest.approx(tb, rel=0.08)
    if fam == "triangular":
        assert _params(rep, fam)["mode"] == pytest.approx(14, abs=1.5)
    # the chosen family is ranked close to the top (not necessarily first: no "this family must win")
    assert candidate(rep, fam)["delta_aic"] < 15 or fam == "triangular"


def test_every_candidate_is_engine_compatible():
    rep = fit_candidates(RNG.gamma(9, 5, 300).tolist(), "s")
    ta = TypeAdapter(Duration)
    for c in rep["candidates"]:
        if c["status"] == "OK":
            d = ta.validate_python({**c["params"], "unit": "s"})
            assert d.mean_seconds() == pytest.approx(c["plausibility"]["fitted_mean"], rel=1e-6)


def test_ranking_suggestion_needs_engineer_and_reports_evidence():
    rep = fit_candidates(RNG.gamma(9, 5, 200).tolist(), "s")
    assert rep["suggested"]["status"] == "SUGGESTED_CANDIDATE - REQUIRES ENGINEER ACCEPTANCE"
    ranks = [c["rank"] for c in rep["candidates"] if "rank" in c]
    assert ranks == sorted(ranks)
    c = rep["candidates"][0]
    assert {"ks_stat", "ks_p_nominal", "ad_stat", "cvm_stat", "cvm_p_nominal"} <= set(c["gof"])
    assert "nominales" in c["gof"]["p_values_note"]
    assert {"aic", "bic", "loglik", "qq", "plausibility"} <= set(c)
    assert set(c["plausibility"]["fitted_quantiles"]) == {"P1", "P50", "P95", "P99", "P99.9"}


def test_normal_with_negative_mass_requires_truncation_and_is_never_suggested():
    rep = fit_candidates(RNG.normal(20, 9, 300).clip(0.5).tolist(), "s")
    n = candidate(rep, "normal")
    assert n["status"] == "REQUIRES_TRUNCATION"
    assert any(f["code"] == "NEGATIVE_SUPPORT" and f["severity"] == "CRITICAL" for f in n["plausibility"]["flags"])
    assert rep["suggested"]["family"] != "normal"


def test_heavy_tail_and_mean_mismatch_are_flagged():
    x = RNG.normal(60, 3, 200).tolist()
    e = candidate(fit_candidates(x, "s"), "exponential")
    codes = {f["code"] for f in e["plausibility"]["flags"]}
    assert "MASS_BELOW_OBSERVED_MIN" in codes and "TAIL_EXTRAPOLATION" in codes


def test_zeros_make_positive_families_not_applicable():
    x = [0.0] + RNG.gamma(9, 5, 50).tolist()
    rep = fit_candidates(x, "s")
    for fam in ("lognormal", "gamma", "weibull"):
        assert candidate(rep, fam)["status"] == "NOT_APPLICABLE"


def test_fit_failure_is_reported_not_hidden(monkeypatch):
    real = fitting._fit_family

    def boom(name, a):
        if name == "weibull":
            raise RuntimeError("optimizer did not converge")
        return real(name, a)
    monkeypatch.setattr(fitting, "_fit_family", boom)
    rep = fit_candidates(RNG.gamma(9, 5, 80).tolist(), "s")
    w = candidate(rep, "weibull")
    assert w["status"] == "FIT_FAILED" and "converge" in w["reason"]
    assert rep["suggested"] is not None


def test_small_samples_warn_but_do_not_block():
    tiny = fit_candidates([30.0, 31.0, 29.5, 32.0], "s")
    assert tiny["candidates"] == [] and tiny["size_class"] == "VERY_SMALL_SAMPLE" and tiny["options"]["EMPIRICAL"]["n"] == 4
    small = fit_candidates(RNG.gamma(9, 5, 8).tolist(), "s")
    assert small["candidates"] and any("VERY_SMALL_SAMPLE" in n for n in small["notes"])
    assert fit_candidates(RNG.gamma(9, 5, 20).tolist(), "s")["size_class"] == "SMALL_SAMPLE"
    assert stats.size_class(30) == "USABLE_WITH_CAUTION" and stats.size_class(100) == "LARGER_SAMPLE"


def test_constant_data_only_deterministic():
    rep = fit_candidates([120.0] * 30, "s")
    assert rep["candidates"] == [] and rep["options"]["DETERMINISTIC"]["MEAN"] == 120


def test_fit_id_is_deterministic():
    x = RNG.gamma(9, 5, 60).tolist()
    assert fit_candidates(x, "s")["fit_id"] == fit_candidates(list(x), "s")["fit_id"]
    assert fit_candidates(x, "s")["fit_id"] != fit_candidates(x, "min")["fit_id"]


# ------------------------------------------------------------------------------------------------- stats
def test_descriptive_statistics():
    x = list(range(1, 101))
    d = stats.describe(x)
    assert d["n"] == 100 and d["mean"] == 50.5 and d["median"] == 50.5 and d["min"] == 1 and d["max"] == 100
    assert d["iqr"] == pytest.approx(49.5) and d["cv"] == pytest.approx(d["std"] / 50.5) and d["p99"] is not None
    small = stats.describe([1.0, 2.0, 3.0])
    assert small["p99"] is None and small["p5"] is None and small["iqr"] is None  # not computed without support in the data
    assert stats.describe([])["n"] == 0


def test_lag1_detects_serial_dependence():
    e = RNG.normal(0, 1, 300)
    ar = np.zeros(300)
    for i in range(1, 300):
        ar[i] = 0.7 * ar[i - 1] + e[i]
    assert stats.lag1((ar + 50).tolist())["flag"] == "POSSIBLE_SERIAL_DEPENDENCE"
    assert stats.lag1((e + 50).tolist())["flag"] == "NO_EVIDENCE_OF_SERIAL_DEPENDENCE"


def test_bootstrap_is_reproducible_and_brackets_the_mean():
    x = RNG.gamma(9, 5, 80).tolist()
    a, b = stats.bootstrap(x, seed=7), stats.bootstrap(x, seed=7)
    assert a == b and a["mean"][0] < float(np.mean(x)) < a["mean"][1]
    assert stats.bootstrap(x[:5])["evaluated"] is False


def test_group_comparison_flags_different_groups():
    g = {"A": RNG.gamma(25, 2, 60).tolist(), "B": (RNG.gamma(25, 2, 60) * 1.3).tolist()}
    assert stats.group_comparison(g)["flag"] == "GROUPS_DIFFER"


def test_plot_data_keeps_order():
    x = [5.0, 1.0, 3.0]
    p = stats.plot_data(x, ["t1", "t2", "t3"])
    assert p["sequence"]["value"] == x and p["ecdf"]["x"] == [1.0, 3.0, 5.0] and sum(p["histogram"]["counts"]) == 3
    assert x == [5.0, 1.0, 3.0]  # never sorted destructively


def test_outliers_detected_never_removed():
    x = RNG.normal(60, 5, 80).tolist()
    x[10], x[40], x[70] = 240.0, 300.0, 5.0
    r = outliers.detect(x, list(range(80)))
    idx = {c["index"] for c in r["candidates"]}
    assert {10, 40, 70} <= idx and len(x) == 80
    assert all(any(m.startswith(("IQR", "MAD")) for m in c["methods"]) for c in r["candidates"])
