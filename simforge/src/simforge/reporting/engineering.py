"""Engineering reports (1.1-D, C12): run engineering report and scenario comparison report.

SOURCE SERVICES -> REPORT MODEL (typed) -> RENDERER (Markdown; HTML from the same Markdown).
The report creates no evidence. Every number is taken verbatim from an existing source:
  * results workbench (1.1-C)            -> KPIs, replications, entity tables, factual observations
  * compare_physical_runs (1.1-A)        -> baseline / alternative / delta, pairing, uncertainty, comparability
  * stored economic evaluations / compare_evaluations (0.9) -> coverage, evaluated_total_cost, savings, payback...
  * build_manifest (1.0)                 -> reproducibility identity
No formula is re-implemented here; missing evidence is written as NOT_AVAILABLE / NOT_EVALUATED, never as 0.
Text is deterministic (no LLM) and descriptive (no recommendation, ranking or preferred scenario).
The 1.0 run report (reporting.report.build_markdown) is unchanged and still produced by `project report`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..analytics.run_comparison import PhysicalComparison, RunIdentity
from ..analytics.workbench import KpiValue, Workbench, fmt_value

REPORT_FORMAT = "1.1-D/1"
VALIDATION_STATEMENT = (
    "SimForge capabilities are SYNTHETICALLY_VALIDATED by automated tests; nothing in this report is "
    "REAL_DATA_VALIDATED. Real-data economic validation: NOT_EXECUTED. Whether the model represents the real system is "
    "the engineer's validation, not established by SimForge.")
GAP_LIMITATION = ("Not stored by the engine (PHYSICAL_KPI_GAP, accepted limitation): setup transitions from -> to; queue "
                  "/ WIP over time; waiting per resource requester; traces outside debug mode. Shown as NOT_AVAILABLE.")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationStatus(_Strict):
    software: Literal["SYNTHETICALLY_VALIDATED"] = "SYNTHETICALLY_VALIDATED"
    real_data: Literal["NOT_REAL_DATA_VALIDATED"] = "NOT_REAL_DATA_VALIDATED"
    real_economic_validation: Literal["NOT_EXECUTED"] = "NOT_EXECUTED"
    model_approval: Literal["APPROVED", "NOT_APPROVED", "NOT_AVAILABLE"]
    statement: str = VALIDATION_STATEMENT


class Verification(_Strict):
    readiness: str
    errors: int
    warnings: int
    summary: str


class RunSide(_Strict):
    """Identity of one run inside a report: comparison identity + reproducibility manifest (both from sources)."""
    identity: RunIdentity
    project: str
    model_version_hash_checked: bool  # the stored model version has exactly the run's physical hash
    verification: Verification | None = None
    validation: ValidationStatus
    manifest: dict[str, Any]


class ProvenanceRow(_Strict):
    path: str
    status: str  # existing ValueStatus value or MISSING
    source: str | None = None
    note: str | None = None
    dataset: str | None = None  # dataset_id@version when the value is derived from imported data
    basis: str | None = None
    decision: str | None = None


class ConfigItem(_Strict):
    """A configuration fact copied from the model version of the run (not a result)."""
    section: Literal["products", "setups", "maintenance", "calendars"]
    entity: str
    facts: dict[str, Any]


class EconomicEvaluationSummary(_Strict):
    evaluation_id: str
    status: str
    currency: str
    economic_hash: str
    economics_engine_version: str
    evaluated_total_cost: dict[str, Any] | None  # stored statistics, verbatim
    included_categories: list[str]
    coverage: dict[str, str]
    annualized: dict[str, Any]
    capex: dict[str, Any]


class RunEngineeringReport(_Strict):
    format: str = REPORT_FORMAT
    kind: Literal["RUN_ENGINEERING_REPORT"] = "RUN_ENGINEERING_REPORT"
    generated_at: str  # NOT part of the reproducibility identity
    run: RunSide
    workbench: Workbench
    configuration: list[ConfigItem]
    provenance: list[ProvenanceRow]
    assumptions: list[dict[str, Any]]
    missing: list[dict[str, Any]]
    economics: list[EconomicEvaluationSummary]
    limitations: list[str]


class EconomicComparisonSection(_Strict):
    status: Literal["AVAILABLE", "NOT_EVALUATED", "NOT_AVAILABLE"]
    reason: str | None = None
    baseline_evaluation: str | None = None
    alternative_evaluation: str | None = None
    comparison: dict[str, Any] | None = None  # compare_evaluations(...).to_dict(), verbatim


class ScenarioComparisonReport(_Strict):
    format: str = REPORT_FORMAT
    kind: Literal["SCENARIO_COMPARISON_REPORT"] = "SCENARIO_COMPARISON_REPORT"
    generated_at: str
    baseline: RunSide
    alternative: RunSide
    physical: PhysicalComparison
    economics: EconomicComparisonSection
    limitations: list[str]
    note: str = "Facts only: deltas are alternative - baseline. Scenarios are described side by side, not ranked; the engineer decides."


# ------------------------------------------------------------------------------------------------ builders
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_side(project, app, run_id: str, identity: RunIdentity) -> tuple[RunSide, Any]:
    from .manifest import build_manifest
    manifest = build_manifest(project, run_id)
    model = app._stored_model_of(project, run_id)
    verification = None
    approval: Literal["APPROVED", "NOT_APPROVED", "NOT_AVAILABLE"] = "NOT_AVAILABLE"
    if model is not None:
        rep = app.validate_model(model)
        verification = Verification(readiness=rep.readiness.value, errors=len(rep.errors), warnings=len(rep.warnings),
                                    summary=rep.summary())
        approval = "APPROVED" if model.is_approved else "NOT_APPROVED"
    side = RunSide(identity=identity, project=project.meta.slug, model_version_hash_checked=model is not None,
                   verification=verification, validation=ValidationStatus(model_approval=approval), manifest=manifest)
    return side, model


def provenance_rows(model) -> list[ProvenanceRow]:
    """Every value carrying a provenance (verbatim) + required parameters without value + declared MISSING items."""
    rows: list[ProvenanceRow] = []

    def walk(x: Any, path: str) -> None:
        if isinstance(x, dict):
            prov = x.get("provenance")
            if isinstance(prov, dict) and prov:
                d = prov.get("data") or {}
                rows.append(ProvenanceRow(
                    path=path, status=str(prov.get("status")), source=prov.get("source"), note=prov.get("note"),
                    dataset=f"{d['dataset_id']}@{d['dataset_version']}" if d.get("dataset_id") else None,
                    basis=d.get("basis"), decision=d.get("decision")))
            for k, v in x.items():
                if k != "provenance":
                    walk(v, f"{path}.{k}" if path else k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}.{v['id'] if isinstance(v, dict) and 'id' in v else i}")
    walk(model.model_dump(mode="json", exclude={"approval": True, "meta": True, "assumptions": True, "missing": True}), "")
    for p in model.parameters:
        if p.value is None:
            rows.append(ProvenanceRow(path=f"parameters.{p.id}.value", status="MISSING", note=p.description or None))
    for m in model.missing:
        rows.append(ProvenanceRow(path=m.path or "-", status="MISSING", note=m.question))
    return rows


def configuration_items(model) -> list[ConfigItem]:
    out: list[ConfigItem] = []
    prod = getattr(model, "production", None)
    if prod is not None:
        for pid, ps in prod.products.items():
            out.append(ConfigItem(section="products", entity=pid, facts={
                "setup_key": ps.setup_key,
                "processing_nodes": sorted(n for n, by in prod.processing.items() if pid in by),
                "route": prod.routes[pid].model_dump(mode="json") if pid in prod.routes else None}))
        for nid, s in prod.setups.items():
            out.append(ConfigItem(section="setups", entity=nid, facts={
                "mode": s.mode, "initial_state": s.initial_state, "at_unavailability": s.at_unavailability,
                "resources": [u.resource for u in s.resources],
                "declared_transitions": sum(len(v) for v in s.matrix.values()) + len(s.by_target) + len(s.from_unconfigured)
                + (1 if s.constant is not None else 0)}))
    mt = getattr(model, "maintenance", None)
    if mt is not None:
        for nid, nm in mt.nodes.items():
            f = nm.failure
            out.append(ConfigItem(section="maintenance", entity=nid, facts={
                "failure_clock": f.clock if f else None, "time_to_failure": f.time_to_failure.describe() if f else None,
                "repair_time": f.repair_time.describe() if f else None,
                "repair_age_effect": f.repair_age_effect if f else None,
                "repair_resources": [u.resource for u in f.repair_resources] if f else [],
                "preventive_tasks": [t.id for t in nm.preventive]}))
    av = getattr(model, "availability", None)
    if av is not None:
        for c in av.calendars:
            out.append(ConfigItem(section="calendars", entity=c.id, facts={
                "working_days": sorted(c.weekly), "breaks": len(c.breaks), "exceptions": len(c.exceptions),
                "resources": sorted(r for r, cid in av.resources.items() if cid == c.id),
                "nodes": sorted(n for n, cid in av.nodes.items() if cid == c.id)}))
    return out


def economic_summary(ev) -> EconomicEvaluationSummary:
    return EconomicEvaluationSummary(
        evaluation_id=ev.evaluation_id, status=ev.status, currency=ev.currency, economic_hash=ev.economic_hash,
        economics_engine_version=ev.economics_engine_version, evaluated_total_cost=ev.totals.get("evaluated_total_cost"),
        included_categories=list(ev.totals.get("included_categories", [])), coverage=dict(ev.coverage),
        annualized=dict(ev.annualized), capex=dict(ev.capex))


def _limitations(side: RunSide, wb: Workbench | None) -> list[str]:
    out = [GAP_LIMITATION]
    if not side.model_version_hash_checked:
        out.append("The model of this run is not stored as a project version with the same hash: configuration, "
                   "provenance and verification sections are NOT_AVAILABLE.")
    if wb is not None and wb.replications == 1:
        out.append("Single replication: no standard deviation or confidence interval (not conclusive for a stochastic model).")
    out.append("Values without a declared provenance are not listed in the provenance section (their origin is not "
               "recorded in the model).")
    return out


def build_run_report(app, project, run_id: str) -> RunEngineeringReport:
    wb = app.results_workbench(project, run_id)
    side, model = run_side(project, app, run_id, wb.run)
    evals = [economic_summary(project.load_evaluation(e["evaluation_id"])) for e in project.evaluations(run_id)]
    return RunEngineeringReport(
        generated_at=_now(), run=side, workbench=wb,
        configuration=configuration_items(model) if model is not None else [],
        provenance=provenance_rows(model) if model is not None else [],
        assumptions=[a.model_dump(mode="json") for a in model.assumptions] if model is not None else [],
        missing=[m.model_dump(mode="json") for m in model.missing] if model is not None else [],
        economics=evals, limitations=_limitations(side, wb))


def _economics_section(app, project, b_run: str, a_run: str, b_eval: str | None, a_eval: str | None) -> EconomicComparisonSection:
    bl, al = project.evaluations(b_run), project.evaluations(a_run)
    if b_eval is None and a_eval is None and not bl and not al:
        return EconomicComparisonSection(status="NOT_EVALUATED", reason="neither run has an economic evaluation")
    if b_eval is None:
        if len(bl) != 1:
            return EconomicComparisonSection(status="NOT_EVALUATED" if not bl else "NOT_AVAILABLE",
                                             reason="baseline run: " + ("no economic evaluation" if not bl else
                                                                         f"{len(bl)} evaluations, choose one explicitly"))
        b_eval = bl[0]["evaluation_id"]
    if a_eval is None:
        if len(al) != 1:
            return EconomicComparisonSection(status="NOT_EVALUATED" if not al else "NOT_AVAILABLE",
                                             baseline_evaluation=b_eval,
                                             reason="alternative run: " + ("no economic evaluation" if not al else
                                                                            f"{len(al)} evaluations, choose one explicitly"))
        a_eval = al[0]["evaluation_id"]
    eb, ea = project.load_evaluation(b_eval), project.load_evaluation(a_eval)
    if (eb.run_id, ea.run_id) != (b_run, a_run):
        return EconomicComparisonSection(status="NOT_AVAILABLE", baseline_evaluation=b_eval, alternative_evaluation=a_eval,
                                         reason="the chosen evaluations do not belong to the compared runs")
    cmp = app.compare_economics(project, b_eval, a_eval)
    return EconomicComparisonSection(status="AVAILABLE", baseline_evaluation=b_eval, alternative_evaluation=a_eval,
                                     comparison=cmp.to_dict())


def build_comparison_report(app, project, baseline_run: str, alternative_run: str,
                            baseline_evaluation: str | None = None, alternative_evaluation: str | None = None) -> ScenarioComparisonReport:
    phys = app.compare_runs(project, baseline_run, alternative_run)
    bside, _ = run_side(project, app, baseline_run, phys.baseline)
    aside, _ = run_side(project, app, alternative_run, phys.alternative)
    econ = _economics_section(app, project, baseline_run, alternative_run, baseline_evaluation, alternative_evaluation)
    lim = [GAP_LIMITATION]
    if phys.comparison_mode != "PAIRED":
        lim.append(f"Comparison mode {phys.comparison_mode}: difference of means only, no paired interval.")
    if econ.status != "AVAILABLE":
        lim.append(f"Economics {econ.status}: {econ.reason}. Physical results are reported without monetary figures.")
    return ScenarioComparisonReport(generated_at=_now(), baseline=bside, alternative=aside, physical=phys, economics=econ,
                                    limitations=lim)


# ------------------------------------------------------------------------------------------------ renderer
def _v(x: Any) -> str:
    if x is None:
        return "NOT_AVAILABLE"
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def _kv(v: KpiValue) -> str:
    return v.status if v.status != "AVAILABLE" else fmt_value(v.name, v.unit, v.mean)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    def cell(s: str) -> str:
        return str(s).replace("|", "/").replace("\n", " ")
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers),
            *["| " + " | ".join(cell(c) for c in r) + " |" for r in rows], ""]


def _block(h: str | None, s: RunSide) -> str:
    """Hash of an optional model block: NO_BLOCK when the run's model has no such block (not missing evidence)."""
    if h is not None:
        return f"`{h}`"
    return "NO_BLOCK" if s.model_version_hash_checked else "NOT_AVAILABLE"


def _side_lines(title: str, s: RunSide) -> list[str]:
    i = s.identity
    m = s.manifest
    rows = [["project", s.project], ["run_id", f"`{i.run_id}`"], ["model version", _v(i.model_version)],
            ["scenario", i.scenario or "none (not a named scenario head)"],
            ["is the project baseline version", _v(i.is_baseline_version)],
            ["physical model hash", f"`{i.model_hash}`"], ["engine", f"{i.engine} {i.engine_version}"],
            ["SimForge version of the run", i.app_version], ["horizon (s)", _v(i.horizon_s)], ["warm-up (s)", _v(i.warmup_s)],
            ["replications", str(i.replications)], ["seeds", ", ".join(str(x) for x in i.seeds)],
            ["availability (calendar) hash", _block(i.availability_hash, s)],
            ["production hash", _block(m.get("production_hash"), s)],
            ["maintenance hash", _block(m.get("maintenance_hash"), s)], ["run started", i.started_at],
            ["model approval", s.validation.model_approval],
            ["verification", s.verification.summary if s.verification else "NOT_AVAILABLE"]]
    return [f"### {title}", "", *_table(["Field", "Value"], rows)]


def _validation_lines(v: ValidationStatus) -> list[str]:
    return ["## Validation status", "", f"- Software: **{v.software}**", f"- Real data: **{v.real_data}**",
            f"- Real economic validation: **{v.real_economic_validation}**", f"- Model approval: **{v.model_approval}**",
            f"- {v.statement}", ""]


def render_run_markdown(r: RunEngineeringReport) -> str:
    wb = r.workbench
    L = [f"# Run engineering report — run {r.run.identity.run_id}", "",
         f"*Report format {r.format} · generated {r.generated_at} (generation time is not part of the run identity)*", ""]
    L += _validation_lines(r.run.validation)
    L += ["## Identity", "", *_side_lines("Run", r.run)]
    L += ["## KPI overview (stored statistics)", "", wb.uncertainty, "",
          *_table(["Metric", "Unit", "Status", "n", "Mean", "Std", "95% CI low", "95% CI high"],
                  [[v.metric, v.unit or "-", v.status, str(v.n) if v.status != "NOT_AVAILABLE" else "NOT_AVAILABLE",
                    _v(v.mean), _v(v.std), _v(v.ci95_low), _v(v.ci95_high)]
                   for v in wb.overview])]
    if wb.replications > 1:
        L += ["## Replications (stored values)", "",
              *_table(["Metric", *[f"rep {i + 1} (seed {s})" for i, s in enumerate(r.run.identity.seeds)]],
                      [[v.metric, *[_v(x) for x in v.replications]] for v in wb.overview if v.status != "NOT_AVAILABLE"])]
    for t in wb.tables:
        L += [f"## {t.title}", "", *_table([t.scope, *t.columns], [[row.entity, *[_kv(row.values[c]) for c in t.columns]] for row in t.rows])]
        if t.key == "setup" and wb.system_setup:
            L += _table(["Metric", "Value"], [[v.metric, _kv(v)] for v in wb.system_setup])
    if wb.observations:
        L += ["## Factual observations", "", *[f"- {o.text}" for o in wb.observations], ""]
    for section in ("products", "setups", "maintenance", "calendars"):
        items = [c for c in r.configuration if c.section == section]
        if items:
            keys = list(items[0].facts)
            L += [f"## Configuration: {section} (model version of the run, not a result)", "",
                  *_table(["Entity", *keys], [[c.entity, *[_v(c.facts[k]) for k in keys]] for c in items])]
    if any(c.section == "setups" for c in r.configuration):
        L += ["Setup transitions from -> to of this run: **NOT_AVAILABLE** (not stored by the engine).", ""]
    L += ["## Data provenance", ""]
    L += (_table(["Value path", "Status", "Source", "Dataset", "Basis", "Decision", "Note"],
                 [[p.path, p.status, _v(p.source), _v(p.dataset), _v(p.basis), _v(p.decision), _v(p.note)] for p in r.provenance])
          if r.provenance else ["No value with a declared provenance and nothing MISSING.", ""])
    L += ["## Assumptions", ""]
    L += ([f"- [{'accepted' if a.get('accepted') else 'open'}] {a.get('text')}" + (f" (`{a['path']}`)" if a.get("path") else "")
           for a in r.assumptions] + [""] if r.assumptions else ["No recorded assumptions.", ""])
    L += ["## Economic evaluations of this run", ""]
    if r.economics:
        L += _table(["Evaluation", "Status", "Currency", "evaluated_total_cost (mean)", "Included categories", "Coverage",
                     "Annualization", "CAPEX", "Economic hash"],
                    [[f"`{e.evaluation_id}`", e.status, e.currency,
                      _v((e.evaluated_total_cost or {}).get("mean")) if e.evaluated_total_cost else "NOT_AVAILABLE",
                      ", ".join(e.included_categories) or "NOT_AVAILABLE",
                      ", ".join(f"{k}={v}" for k, v in sorted(e.coverage.items())),
                      _v(e.annualized.get("status")), _v(e.capex.get("total") if not e.capex.get("missing") else "MISSING"),
                      f"`{e.economic_hash}`"] for e in r.economics])
    else:
        L += ["NOT_EVALUATED: no economic evaluation of this run (not a zero cost).", ""]
    L += ["## Limitations", "", *[f"- {x}" for x in r.limitations], "",
          "## Reproducibility manifest", "", "```json", _json(r.run.manifest), "```", ""]
    return "\n".join(L)


def _json(d: dict) -> str:
    import json
    return json.dumps(d, indent=2, sort_keys=True, default=str)


def render_comparison_markdown(r: ScenarioComparisonReport) -> str:
    p = r.physical
    L = [f"# Scenario comparison report — {p.baseline.run_id} (baseline) vs {p.alternative.run_id} (alternative)", "",
         f"*Report format {r.format} · generated {r.generated_at} (generation time is not part of the run identities)*", "",
         f"> {r.note}", ""]
    L += _validation_lines(r.baseline.validation)
    if r.alternative.validation.model_approval != r.baseline.validation.model_approval:
        L += [f"- Alternative model approval: **{r.alternative.validation.model_approval}**", ""]
    L += ["## Identities", "", *_side_lines("Baseline", r.baseline), *_side_lines("Alternative", r.alternative)]
    L += ["## Comparability", "", f"- Status: **{p.status}**", f"- Mode: **{p.comparison_mode}**",
          *[f"- Pairing evidence: {e}" for e in p.pairing_evidence], ""]
    L += (_table(["Level", "Check", "Detail"], [[c.level, c.check, c.detail] for c in p.checks]) if p.checks else ["No checks raised.", ""])
    L += ["## Physical comparison", "", f"{p.delta_convention}.", "",
          *_table(["Metric", "Unit", "Status", "Baseline", "Alternative", "Delta", "Mode", "n", "Std", "95% CI low", "95% CI high", "Reason"],
                  [[m.metric, m.unit or "-", m.status, _v(m.baseline_mean), _v(m.alternative_mean),
                    _v(m.delta.mean) if m.delta else "NOT_AVAILABLE", m.delta.mode if m.delta else "-",
                    str(m.delta.n) if m.delta else "-", _v(m.delta.std) if m.delta else "-",
                    _v(m.delta.ci95_low) if m.delta else "-", _v(m.delta.ci95_high) if m.delta else "-", m.reason or ""]
                   for m in p.metrics])]
    e = r.economics
    L += ["## Economics", "", f"- Status: **{e.status}**" + (f" — {e.reason}" if e.reason else "")]
    if e.status == "AVAILABLE" and e.comparison:
        c = e.comparison
        L += [f"- Evaluations: `{e.baseline_evaluation}` (baseline) vs `{e.alternative_evaluation}` (alternative)",
              f"- Comparison status: **{c['status']}** · paired: {c['paired']} · coverage match: {c['coverage_match']}", ""]
        L += _table(["Check level", "Check", "Detail"], [[x["level"], x["check"], x["detail"]] for x in c.get("checks", [])]) \
            if c.get("checks") else []
        L += ["### evaluated cost deltas (common categories; delta = alternative - baseline)", "",
              *_table(["Category", "Mode", "Mean", "95% CI low", "95% CI high"],
                      [[k, _v(v.get("mode")), _v(v.get("mean")), _v(v.get("ci95_low")), _v(v.get("ci95_high"))]
                       for k, v in c["cost_deltas"].items()])]
        mism = c.get("mismatched_categories", {})
        L += [f"- Savings ({c['savings'].get('definition')}): {_v(c['savings'].get('mean'))}",
              f"- Categories only in baseline: {', '.join(mism.get('only_baseline', [])) or 'none'} · only in alternative: "
              f"{', '.join(mism.get('only_alternative', [])) or 'none'} (missing categories are never 0)",
              f"- Annual: {c['annual'].get('status')}" + (f" — {c['annual'].get('reason')}" if c['annual'].get('reason') else ""),
              f"- CAPEX: {c['capex'].get('status')}" + (f" · incremental {_v(c['capex'].get('incremental'))}" if 'incremental' in c['capex'] else ""),
              f"- Simple payback: {c['payback'].get('status')}" + (f" · {_v(c['payback'].get('years'))} years" if 'years' in c['payback'] else "")
              + (f" — {c['payback'].get('reason')}" if c['payback'].get('reason') else ""),
              f"- Annual return on incremental CAPEX: {c['annual_return_on_incremental_capex'].get('status')}"
              + (f" · {_v(c['annual_return_on_incremental_capex'].get('value'))}" if 'value' in c['annual_return_on_incremental_capex'] else ""),
              ""]
    else:
        L += ["- No monetary comparison: economics NOT_EVALUATED / NOT_AVAILABLE is not a zero cost.", ""]
    L += ["## Limitations", "", *[f"- {x}" for x in r.limitations], "",
          "## Reproducibility manifests", "", "### Baseline", "```json", _json(r.baseline.manifest), "```",
          "### Alternative", "```json", _json(r.alternative.manifest), "```", ""]
    return "\n".join(L)


def render_html(markdown: str, title: str) -> str:
    """HTML from the SAME Markdown (same values and states; only the format changes)."""
    from .report import markdown_to_html
    return markdown_to_html(_code_blocks_as_quotes(markdown), title)


def _code_blocks_as_quotes(md: str) -> str:
    # the 1.0 converter has no fenced blocks: keep the JSON manifest lines verbatim as paragraphs
    out, inside = [], False
    for ln in md.splitlines():
        if ln.startswith("```"):
            inside = not inside
            continue
        out.append(f"`{ln}`" if inside and ln.strip() else ln)
    return "\n".join(out)


class ReportFiles(_Strict):
    markdown: str
    html: str
    json_model: str = Field(description="the typed report model (JSON) the renderers used")
