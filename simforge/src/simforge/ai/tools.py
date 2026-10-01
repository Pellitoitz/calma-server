"""Controlled tools for an AI orchestrator. The LLM never executes arbitrary code: it can only call these
functions, with arguments validated by strict schemas, against ONE project.

    search_components  inspect_component  create_model_spec  update_model_spec  validate_model
    compare_models     run_simulation     run_experiment     get_results

Deliberately missing: approving a model (engineer only), modifying the library (engineer only), executing
code or SimPy, reading files. `definitions()` returns the tools in Anthropic tool-use format; `call()`
validates and dispatches, and always returns JSON-serialisable data (errors included, never exceptions).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.isms import ExperimentSpec, Factor
from .schemas import EditOp, EditPlan

if TYPE_CHECKING:  # pragma: no cover
    from ..persistence.project import Project
    from ..services.app import SimForgeApp


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchComponents(_Args):
    query: str = Field(description="words describing the element, any language (e.g. 'buffer de entrada', 'shared operator')")
    category: str | None = None


class InspectComponent(_Args):
    component_id: str
    version: str | None = None


class CreateModelSpec(_Args):
    description: str = Field(description="the engineer's process description, verbatim")


class Change(_Args):
    path: str = Field(description="ISMS path, preferably parameters.<id>.value")
    value: Any
    expected: Any | None = Field(default=None, description="current value stated by the engineer, checked before applying")


class UpdateModelSpec(_Args):
    request: str = Field(description="the engineer's request, verbatim (stored with the change)")
    changes: list[Change] = Field(min_length=1)
    confirm: bool = False


class ValidateModel(_Args):
    pass


class CompareModels(_Args):
    version_a: int
    version_b: int
    run: bool = True


class RunSimulation(_Args):
    replications: int | None = Field(default=None, ge=1, le=100)


class RunExperiment(_Args):
    factor_path: str
    values: list[float] = Field(min_length=1, max_length=50)


class GetResults(_Args):
    run_id: str | None = Field(default=None, description="omit for the latest run")


@dataclass
class Tool:
    name: str
    description: str
    args: type[_Args]
    handler: Callable[[Any], Any]


class ToolRegistry:
    def __init__(self, app: "SimForgeApp", project: "Project"):
        self.app, self.project = app, project
        self.tools: dict[str, Tool] = {t.name: t for t in [
            Tool("search_components", "Search the validated component library and rule catalog. Always search before proposing anything new.",
                 SearchComponents, self._search),
            Tool("inspect_component", "Parameters, defaults, KPIs, validation status and tests of one library component.",
                 InspectComponent, self._inspect),
            Tool("create_model_spec", "Interpret a description into a new ISMS version built from library components. Returns matching "
                 "report, build plan, grouped missing-data questions and readiness. Never invents values.", CreateModelSpec, self._create),
            Tool("update_model_spec", "Apply structured changes to the current ISMS (new version, diff returned).", UpdateModelSpec,
                 self._update),
            Tool("validate_model", "Verify the current model: readiness, errors, warnings, assumptions.", ValidateModel, self._validate),
            Tool("compare_models", "Structural (and, if equivalent, result) comparison of two versions of the project.", CompareModels,
                 self._compare),
            Tool("run_simulation", "Run the current model. Fails if an engineer has not approved the AI-generated model.",
                 RunSimulation, self._run),
            Tool("run_experiment", "Run a one-factor experiment on the current model.", RunExperiment, self._experiment),
            Tool("get_results", "KPIs of a stored run (computed by the engine, never by the AI).", GetResults, self._results),
        ]}

    def definitions(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description, "input_schema": t.args.model_json_schema()} for t in self.tools.values()]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool '{name}'", "available": sorted(self.tools)}
        try:
            args = tool.args.model_validate(arguments or {})
        except ValidationError as e:
            return {"ok": False, "error": "invalid arguments", "details": json.loads(e.json(include_url=False))}
        try:
            out = tool.handler(args)
        except Exception as e:  # noqa: BLE001 - tool errors are data for the orchestrator, not crashes
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        self.project.log("ai", f"tool:{name}", request=json.dumps(arguments or {}, default=str)[:2000],
                         result=json.dumps(out, default=str)[:500])
        return {"ok": True, **out}

    # ------------------------------------------------------------------ handlers
    def _search(self, a: SearchComponents) -> dict:
        reg = self.app.registry
        comps = reg.search(a.query, category=a.category)[:8]
        rules = reg.search_rules(a.query)[:5]
        return {"components": [{"id": c.id, "version": c.version, "name": c.name, "behavior": c.behavior.value,
                                "validation_status": c.validation_status.value, "summary": c.description.split("\n")[0][:160]}
                               for c in comps],
                "rules": [{"id": r.id, "version": r.version, "kind": r.kind, "binding": r.binding,
                           "validation_status": r.validation_status.value} for r in rules]}

    def _inspect(self, a: InspectComponent) -> dict:
        c = self.app.registry.get(a.component_id, a.version)
        return {"id": c.id, "version": c.version, "behavior": c.behavior.value, "defaults": c.defaults, "param_docs": c.param_docs,
                "kpis": c.kpis, "validation_status": c.validation_status.value, "tests": c.tests,
                "parameters": list(c.param_schema().get("properties", {}))}

    def _create(self, a: CreateModelSpec) -> dict:
        pr = self.app.parse_process(self.project, a.description)
        o = pr.outcome
        return {"version": pr.version, "readiness": pr.report.readiness.value, "reuse_ratio": o.reuse_ratio,
                "custom_logic_count": o.custom_count, "matching_report": o.matching_report(),
                "build_plan": o.plan.to_text() if o.plan else None, "questions": o.questions(),
                "assumptions": [x.text for x in o.model.assumptions]}

    def _update(self, a: UpdateModelSpec) -> dict:
        ops = [EditOp(intent="set", path=c.path, value_json=json.dumps(c.value),
                      expected_json=None if c.expected is None else json.dumps(c.expected)) for c in a.changes]
        r = self.app.apply_plan(self.project, EditPlan(operations=ops, explanation=a.request), a.request, "tool", a.confirm)
        return {"message": r.message, "new_version": r.new_version, "needs_confirmation": r.needs_confirmation, "error": r.error,
                "changes": [list(c) for c in r.changes]}

    def _validate(self, a: ValidateModel) -> dict:
        model = self.project.current_model()
        if model is None:
            raise ValueError("no model in the project")
        rep = self.app.validate_model(model)
        return {"readiness": rep.readiness.value, "summary": rep.summary(),
                "issues": [{"level": i.level.value, "code": i.code, "message": i.message, "path": i.path} for i in rep.issues]}

    def _compare(self, a: CompareModels) -> dict:
        spec, res = self.app.compare_models(self.project.load_version(a.version_a), self.project.load_version(a.version_b), run=a.run)
        return {"structurally_equivalent": spec.structurally_equivalent, "textual_equal": spec.textual_equal,
                "report": spec.to_text(), "results": res.to_text() if res else None,
                "results_equivalent": res.equivalent if res else None}

    def _run(self, a: RunSimulation) -> dict:
        res = self.app.run_simulation(self.project, replications=a.replications)
        return {"run_id": res.run_id, "kpis": _headline(res)}

    def _experiment(self, a: RunExperiment) -> dict:
        values = [int(v) if float(v).is_integer() else v for v in a.values]
        spec = ExperimentSpec(name=f"tool: {a.factor_path}", factors=[Factor(path=a.factor_path, values=values)])
        res = self.app.run_experiment(self.project, spec)
        return {"experiment_id": res.experiment_id, "table": res.table(["units_completed", "throughput_per_hour", "avg_wip"])}

    def _results(self, a: GetResults) -> dict:
        runs = self.project.runs(1)
        if not a.run_id and not runs:
            raise ValueError("no runs yet")
        res = self.project.load_run(a.run_id or runs[0]["run_id"])
        return {"run_id": res.run_id, "kpis": _headline(res)}


def _headline(res) -> dict[str, float]:
    keys = ["units_completed", "throughput_per_hour", "avg_wip", "avg_lead_time_s", "units_scrapped"]
    return {k: res.kpis.mean(k) for k in keys if k in res.kpis.stats}
