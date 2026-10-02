"""Closure of the data phase: loc audit, uniform/triangular parameter sources, structured truncation, empirical support,
heuristic wording, temporal holdout. SYNTHETIC TEST DATA only."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("openpyxl")

from simforge.data import fitting, stats  # noqa: E402
from simforge.data.fitting import candidate, fit_candidates  # noqa: E402
from simforge.data.service import DataDecisionRequired  # noqa: E402
from simforge.data.store import DatasetError  # noqa: E402
from simforge.domain.io import load_model  # noqa: E402
from simforge.services.app import SimForgeApp  # noqa: E402

ROOT = Path(__file__).parents[1]
SYN = ROOT / "examples" / "data" / "synthetic"
RNG = np.random.default_rng(777)


# ------------------------------------------------------------------------------------------------- loc audit
def test_normal_mean_is_estimated_not_forced_to_zero():
    x = RNG.normal(500, 20, 400).tolist()
    c = candidate(fit_candidates(x, "s"), "normal")
    assert c["params"]["mean"] == pytest.approx(500, rel=0.01) and c["status"] == "OK"
    assert "loc = μ estimada" in c["method"] and c["parameter_sources"]["mean"]["source"] == "ESTIMATED_FROM_DATA"
    d, *_ = fitting._fit_family("normal", np.sort(np.asarray(x)))
    assert d.mean() == pytest.approx(500, rel=0.01)  # scipy loc = mean, not 0


@pytest.mark.parametrize("fam", ["lognormal", "exponential", "gamma", "weibull"])
def test_positive_families_have_no_shift_and_say_so(fam):
    c = candidate(fit_candidates((RNG.gamma(9, 5, 200) + 100).tolist(), "s"), fam)  # data far from 0
    assert c["plausibility"]["support_lower"] == 0.0 and c["method"] == "MLE (loc=0)"
    assert all("loc fijado en 0" in v["method"] for v in c["parameter_sources"].values())


# ------------------------------------------------------------------------------------------- uniform/triangular
def test_uniform_default_is_observed_range_without_hidden_widening():
    x = RNG.uniform(20, 30, 50).tolist()
    c = candidate(fit_candidates(x, "s"), "uniform")
    assert c["params"]["low"] == min(x) and c["params"]["high"] == max(x)
    src = c["parameter_sources"]
    assert src["low"]["source"] == "ESTIMATED_FROM_DATA" and "OBSERVED_RANGE" in src["low"]["method"] and c["k"] == 2


def test_uniform_and_triangular_with_engineer_bounds():
    x = RNG.uniform(20, 30, 50).tolist()
    rep = fit_candidates(x, "s", bounds={"low": 18, "high": 32, "source": "PROCESS_SPECIFICATION"})
    u, t = candidate(rep, "uniform"), candidate(rep, "triangular")
    assert (u["params"]["low"], u["params"]["high"], u["k"]) == (18, 32, 0)
    assert u["parameter_sources"]["high"]["source"] == "PROCESS_SPECIFICATION"
    assert (t["params"]["low"], t["params"]["high"]) == (18, 32) and t["parameter_sources"]["mode"]["source"] == "ESTIMATED_FROM_DATA"
    out = fit_candidates(x, "s", bounds={"low": 22, "high": 32, "source": "ENGINEER_BOUNDS"})
    assert candidate(out, "uniform")["status"] == "NOT_APPLICABLE" and "fuera de los límites" in candidate(out, "uniform")["reason"]
    with pytest.raises(ValueError, match="no se inventan"):
        fit_candidates(x, "s", bounds={"low": 0, "high": 50, "source": "GUESS"})


def test_triangular_calculated_bounds_formula_and_explicit_clip():
    x = [10.0, 12, 14, 15, 18, 20, 25, 30, 40, 60]
    t = candidate(fit_candidates(x, "s"), "triangular")
    sp = (60 - 10) / 9
    assert t["params"]["low"] == pytest.approx(10 - sp) and t["params"]["high"] == pytest.approx(60 + sp)
    assert t["parameter_sources"]["low"]["source"] == "CALCULATED_BOUNDS" and "(n − 1)" in t["parameter_sources"]["low"]["method"]
    y = [0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55]  # widening would go below 0
    t2 = candidate(fit_candidates(y, "s"), "triangular")
    assert t2["params"]["low"] == 0 and "RECORTADO A 0" in t2["parameter_sources"]["low"]["method"]


# ------------------------------------------------------------------------------------------ project fixture
@pytest.fixture
def env(tmp_path):
    sf = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = sf.create_project("cierre")
    sf.save_model(p, load_model(ROOT / "examples" / "data" / "e2e_selective_per_circuit.yaml"), "base")
    return sf, p, sf.data(p)


def test_truncation_bound_type_physical_vs_data_and_mean_shift(env, tmp_path):
    _, _, ds = env
    f = tmp_path / "t.csv"
    f.write_text("t\n" + "\n".join(f"{v:.2f}" for v in RNG.normal(10, 6, 200).clip(0.3)), encoding="utf-8")
    did = ds.import_file(f, "t", "t", "PROCESSING_TIME", "PER_UNIT", unit="s").meta.dataset_id
    fit = ds.fit(did, by="ana")
    acc = ["MASS_BELOW_OBSERVED_MIN", "MEAN_MISMATCH"]
    phys = {"lower": 2, "reason": "el husillo no baja de 2 s", "bound_type": "PHYSICAL_BOUND"}
    with pytest.raises(DataDecisionRequired, match="fuera del límite físico"):
        ds.decide(did, "USE_FITTED", by="ana", fit_id=fit["fit_id"], candidate="normal", truncation=phys, accept_warnings=acc)
    mod = {"lower": 0, "reason": "evitar tiempos negativos", "bound_type": "MODELLING_BOUND"}
    with pytest.raises(DataDecisionRequired, match="TRUNCATION_SHIFTS_MEAN"):
        ds.decide(did, "USE_FITTED", by="ana", fit_id=fit["fit_id"], candidate="normal", truncation=mod, accept_warnings=acc)
    ev = ds.decide(did, "USE_FITTED", by="ana", fit_id=fit["fit_id"], candidate="normal", truncation=mod,
                   accept_warnings=acc + ["TRUNCATION_SHIFTS_MEAN"])
    tr = ev.distribution["truncation"]
    assert tr["bound_type"] == "MODELLING_BOUND" and tr["method"] == "FIT_THEN_TRUNCATE"
    with pytest.raises(DatasetError, match="USE_FITTED"):
        ds.decide(did, "USE_EMPIRICAL", by="ana", truncation=mod)


def test_empirical_small_sample_warns_but_does_not_block(env, tmp_path):
    _, _, ds = env
    f = tmp_path / "s.csv"
    f.write_text("t\n31\n29\n35\n30\n33\n", encoding="utf-8")
    did = ds.import_file(f, "s", "t", "PROCESSING_TIME", "PER_UNIT", unit="s").meta.dataset_id
    ev = ds.decide(did, "USE_EMPIRICAL", by="ana")
    assert ev.distribution["values"] == [31, 29, 35, 30, 33]
    assert any("EMPIRICAL_SMALL_SAMPLE" in w for w in ev.warnings)
    assert any("EMPIRICAL_SUPPORT: [29, 35]" in w for w in ev.warnings)
    info = fit_candidates([31, 29, 35, 30, 33], "s")["options"]["EMPIRICAL"]
    assert (info["observed_min"], info["observed_max"], info["sample_size"], info["support"]) == (29, 35, 5, "OBSERVED_VALUES_ONLY")


def test_parameter_sources_reach_the_model(env):
    sf, p, ds = env
    did = ds.import_file(SYN / "SYNTHETIC_A_constant.csv", "a", "tiempo_s", "PROCESSING_TIME", "PER_CIRCUIT", unit="s").meta.dataset_id
    fit = ds.fit(did, by="ana", bounds={"low": 115, "high": 125, "source": "PROCESS_SPECIFICATION"})
    d = ds.decide(did, "USE_FITTED", by="ana", fit_id=fit["fit_id"], candidate="uniform",
                  accept_warnings=["MEAN_MISMATCH", "MASS_BELOW_OBSERVED_MIN"])
    ds.apply(did, d.decision_id, "nodes.assembly.params.process_time", "PER_CIRCUIT", by="ana", aggregation="sum_iid")
    link = p.current_model().nodes[1].params["process_time"]["provenance"]["data"]
    assert link["parameter_sources"]["low"]["source"] == "PROCESS_SPECIFICATION"


# ------------------------------------------------------------------------------------------ heuristics wording
def test_sample_size_classes_are_heuristics_without_sufficiency_claims():
    for n in (29, 30, 99, 100):
        d = stats.describe(list(range(1, n + 1)))
        assert d["size_class_kind"] == "SIMFORGE_HEURISTIC"
        assert "suficiente" not in d["size_class_meaning"].replace("no implica datos suficientes", "").replace(
            "no es un umbral de suficiencia", "")


def test_serial_flag_is_screening_never_confirmed():
    ar = np.zeros(300)
    e = RNG.normal(0, 1, 300)
    for i in range(1, 300):
        ar[i] = 0.8 * ar[i - 1] + e[i]
    r = stats.lag1((ar + 50).tolist())
    assert r["flag"] == "POSSIBLE_SERIAL_DEPENDENCE" and r["lags_inspected"] == [1] and "SCREENING" in r["method"]
    assert "CONFIRMED" not in str(r)


def test_ranking_text_never_claims_true_distribution():
    from simforge.data.report import fit_text
    t = fit_text(fit_candidates(RNG.gamma(9, 5, 120).tolist(), "s"))
    assert "STATISTICAL RANKING" in t and "NO la distribución verdadera" in t and "SUGGESTED CANDIDATE" in t


# ------------------------------------------------------------------------------------------------ holdout
def test_temporal_holdout_detects_drift_and_scores_out_of_sample(env, tmp_path):
    _, _, ds = env
    first, later = RNG.gamma(16, 2, 140), RNG.gamma(16, 2, 60) * 1.4  # the process slowed down later
    f = tmp_path / "h.csv"
    f.write_text("t\n" + "\n".join(f"{v:.2f}" for v in np.concatenate([first, later])), encoding="utf-8")
    did = ds.import_file(f, "h", "t", "PROCESSING_TIME", "PER_UNIT", unit="s").meta.dataset_id
    h = ds.holdout(did, 0.7, by="ana")
    assert (h["n_train"], h["n_test"]) == (140, 60) and h["train_vs_test"]["flag"] == "POSSIBLE_DRIFT"
    assert "file order" in h["order"] and any(c.get("holdout_rank") == 1 for c in h["candidates"])
    stable = tmp_path / "s.csv"
    stable.write_text("t\n" + "\n".join(f"{v:.2f}" for v in RNG.gamma(16, 2, 200)), encoding="utf-8")
    sid = ds.import_file(stable, "st", "t", "PROCESSING_TIME", "PER_UNIT", unit="s").meta.dataset_id
    assert ds.holdout(sid, 0.7)["train_vs_test"]["flag"] == "NO_CLEAR_DRIFT"
    with pytest.raises(DatasetError):
        ds.holdout(sid, 0.95)
    assert ds.state(sid).fits == [] and ds.state(sid).decisions == []  # a check, never a decision
