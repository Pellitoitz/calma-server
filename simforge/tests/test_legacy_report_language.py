"""D-1 (1.1 line): the legacy 1.0 report describes; it does not prescribe. Its section structure is unchanged."""

from __future__ import annotations

from simforge.domain.io import load_model
from simforge.domain.isms import Assumption, ExperimentSpec, Factor
from simforge.experiments.runner import run_experiment, run_simulation
from simforge.reporting.report import build_markdown
from simforge.validation.verifier import verify

from .conftest import EXAMPLES

PRESCRIPTIVE = ("choose", "recommend", "should", "validate the model", "increase replications", "confirm or correct",
                "before concluding", "before acting", "risks and next steps", "best")


def _report(registry):
    m = load_model(EXAMPLES / "02_shared_operator.yaml")
    m = m.model_copy(update={"assumptions": [Assumption(id="a1", text="operator walking time neglected")]})
    rep = verify(m, registry)[0]
    run = run_simulation(m, registry)
    # two capacities giving the same throughput -> the legacy "tie" sentence is produced
    exp = run_experiment(m, ExperimentSpec(name="ops", factors=[Factor(path="resources.operator_1.quantity", values=[2, 3])],
                                           replications=1), registry)
    return build_markdown(m, rep, run, exp, "demo")


def test_legacy_report_has_no_prescriptive_language(registry):
    md = _report(registry).lower()
    assert not [w for w in PRESCRIPTIVE if w in md]


def test_legacy_report_keeps_its_sections_and_facts(registry):
    md = _report(registry)
    for s in ("## 1. Executive summary", "## 3. Assumptions and missing data", "## 5. Results", "## 7. Experiment",
              "## 8. Economic evaluation", "## 9. Validation status", "## 10. ", "## Reproducibility", "not approved"):
        assert s in md, s
    assert "within 0.5% of the maximum" in md and "not evaluated by this report" in md
    assert "Engineer approval: **NO**" in md and "1 assumption(s) listed in section 3 are not accepted" in md
