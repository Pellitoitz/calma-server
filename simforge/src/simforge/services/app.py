"""Application service: the internal API used by the CLI and the UI.

UI and CLI never touch the engine, the database or the LLM directly; they call
these functions. (A FastAPI layer can wrap this class 1:1 later.)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..ai.compiler import ParseOutcome, compile_draft
from ..ai.context import Anonymizer
from ..ai.interpreter import Interpreter, LLMInterpreter, RuleBasedInterpreter
from ..ai.provider import LLMProvider, LLMUsage, provider_from_env
from ..ai.schemas import EditPlan
from ..analytics.diagnostics import Finding
from ..domain.isms import Approval, ExperimentSpec, Factor, ISMSModel
from ..domain.paths import diff, set_value
from ..experiments.runner import ExperimentResult, SimulationResult, run_experiment, run_simulation, validate_experiment
from ..library.registry import ComponentRegistry
from ..persistence.project import Project, Workspace
from ..validation.verifier import VerificationReport, verify


def default_workspace() -> Path:
    return Path(os.environ.get("SIMFORGE_WORKSPACE", "./workspace")).resolve()


def default_library_dir() -> Path:
    return Path(os.environ.get("SIMFORGE_LIBRARY", Path.home() / ".simforge" / "library"))


@dataclass
class CommandResponse:
    plan: EditPlan
    message: str
    changes: list[tuple[str, Any, Any]] = field(default_factory=list)
    new_version: int | None = None
    needs_confirmation: bool = False
    simulation: SimulationResult | None = None
    experiment: ExperimentResult | None = None
    findings: list[Finding] = field(default_factory=list)
    error: str | None = None


@dataclass
class ParseResponse:
    outcome: ParseOutcome
    report: VerificationReport
    version: int
    interpreter: str


class SimForgeApp:
    def __init__(self, workspace: Path | None = None, library_dir: Path | None = None,
                 provider: LLMProvider | None | str = "auto"):
        self.workspace = Workspace(workspace or default_workspace())
        self.library_dir = library_dir or default_library_dir()
        self.registry = ComponentRegistry.load_default(self.library_dir)
        self.provider = provider_from_env() if provider == "auto" else provider  # type: ignore[assignment]

    # ------------------------------------------------------------- interpreter
    def interpreter(self, project: Project | None = None) -> Interpreter:
        if self.provider is None:
            return RuleBasedInterpreter(self.registry)
        anon = Anonymizer.with_defaults(project.meta.sensitive_terms if project else {})

        def log_usage(u: LLMUsage, purpose: str) -> None:
            if project:
                project.log_llm_usage(u.provider, u.model, purpose, u.input_tokens, u.output_tokens, u.est_cost_usd, u.sent_chars)

        return LLMInterpreter(self.provider, self.registry, anon, log_usage)

    # ----------------------------------------------------------------- projects
    def create_project(self, name: str, description: str = "") -> Project:
        return self.workspace.create_project(name, description)

    def list_projects(self):
        return self.workspace.list_projects()

    def open_project(self, slug: str) -> Project:
        return self.workspace.open_project(slug)

    # ------------------------------------------------------------------- model
    def parse_process(self, project: Project, text: str) -> ParseResponse:
        """Natural language -> draft (AI or rules) -> ISMS (deterministic) -> verification -> new version."""
        interp = self.interpreter(project)
        draft = interp.parse(text)
        outcome = compile_draft(draft, self.registry, text)
        report, _ = verify(outcome.model, self.registry)
        v = project.save_version(outcome.model, message=f"parsed from description ({interp.name})", author="ai")
        project.log("ai", "parse_process", request=text, interpretation=draft.model_dump_json(),
                    change={"components": outcome.component_matches, "reuse_ratio": outcome.reuse_ratio},
                    result=report.summary())
        project.record_metric("reuse_ratio", outcome.reuse_ratio)
        project.record_metric("ai_questions", len([m for m in outcome.model.missing]))
        return ParseResponse(outcome, report, v, interp.name)

    def validate_model(self, model: ISMSModel) -> VerificationReport:
        return verify(model, self.registry)[0]

    def save_model(self, project: Project, model: ISMSModel, message: str, actor: str = "user") -> int:
        prev = project.current_model()
        v = project.save_version(model, message=message, author=actor)
        project.log(actor, "edit" if actor == "user" else "ai_edit", result=f"v{v}: {message}",
                    change=[list(c) for c in diff(prev, model, ignore_provenance=True)] if prev else None)
        return v

    def approve_model(self, project: Project, by: str, note: str = "") -> int:
        model = project.current_model()
        if model is None:
            raise ValueError("No hay modelo que aprobar.")
        rep = self.validate_model(model)
        if not rep.ok:
            raise ValueError("No se puede aprobar un modelo con errores de verificación:\n" + "\n".join(str(i) for i in rep.errors))
        approved = model.model_copy(update={
            "approval": Approval(approved=True, by=by, at=datetime.now(timezone.utc), model_hash=model.content_hash(), note=note),
            "assumptions": [a.model_copy(update={"accepted": True}) for a in model.assumptions],
        })
        v = project.save_version(approved, message=f"engineer approval by {by}", author=by)
        project.log("user", "approve_model", result=f"v{v} approved by {by}")
        if project.metric("time_to_engineer_approval_s") is None:
            first = project.versions()[0].created_at
            delta = datetime.now(timezone.utc) - datetime.fromisoformat(first)
            project.record_metric("time_to_engineer_approval_s", delta.total_seconds())
        return v

    # --------------------------------------------------------------- simulation
    def run_simulation(self, project: Project, model: ISMSModel | None = None, replications: int | None = None,
                       trace: bool | None = None, keep_records: bool = False) -> SimulationResult:
        model = model or project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        res = run_simulation(model, self.registry, replications=replications, trace=trace, cache=project, keep_records=keep_records)
        project.save_run(res, project.meta.current_version)
        project.log("system", "run_simulation", result=f"run {res.run_id}: TH={res.kpis.mean('throughput_per_hour'):.2f}/h")
        return res

    def run_experiment(self, project: Project, spec: ExperimentSpec, model: ISMSModel | None = None,
                       progress: Callable[[int, int], None] | None = None) -> ExperimentResult:
        model = model or project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        res = run_experiment(model, spec, self.registry, cache=project, progress=progress)
        project.save_experiment(res, project.meta.current_version)
        project.log("system", "run_experiment", request=spec.model_dump_json(), result=f"experiment {res.experiment_id}: {len(res.scenarios)} scenarios")
        return res

    # --------------------------------------------------------------- commands
    def command(self, project: Project, text: str, confirm: bool = False) -> CommandResponse:
        """Natural-language command. The ISMS is modified, never 'remembered'."""
        model = project.current_model()
        if model is None:
            pr = self.parse_process(project, text)
            return CommandResponse(EditPlan(explanation="nuevo modelo"), f"Modelo creado (v{pr.version}): {pr.report.summary()}",
                                   new_version=pr.version)
        interp = self.interpreter(project)
        plan = interp.plan_edit(text, model)
        return self.apply_plan(project, plan, text, interp.name, confirm)

    def apply_plan(self, project: Project, plan: EditPlan, request: str, interpreter: str = "", confirm: bool = False) -> CommandResponse:
        model = project.current_model()
        assert model is not None
        if plan.question and not plan.operations:
            return CommandResponse(plan, plan.question)
        sets = [o for o in plan.operations if o.intent == "set"]
        others = [o for o in plan.operations if o.intent != "set"]
        resp = CommandResponse(plan, plan.explanation)
        if sets:
            new = model
            try:
                for op in sets:
                    value = json.loads(op.value_json or "null")
                    if isinstance(value, dict) and "dist" in value and "provenance" not in value:
                        value["provenance"] = {"status": "provided_by_client", "source": "chat",
                                               "note": request[:120], "timestamp": datetime.now(timezone.utc).isoformat()}
                    new = set_value(new, op.path or "", value)
            except Exception as e:  # noqa: BLE001
                return CommandResponse(plan, f"No se pudo aplicar el cambio: {e}", error=str(e))
            changes = diff(model, new, ignore_provenance=True)
            important = len(changes) > 2 or model.is_approved or any(p.startswith("resources.") and n in (0, None) for p, _, n in changes)
            if important and not confirm:
                return CommandResponse(plan, "Cambio importante: requiere confirmación." +
                                       (" El modelo está aprobado; el cambio invalidará la aprobación." if model.is_approved else ""),
                                       changes=changes, needs_confirmation=True)
            v = project.save_version(new, message=f"chat: {request[:80]}", author="ai")
            project.log("ai", "edit", request=request, interpretation=plan.model_dump_json(), change=[list(c) for c in changes], result=f"v{v}")
            resp.changes, resp.new_version = changes, v
            resp.message = "Modelo actualizado (v%d): %s" % (v, "; ".join(f"{p}: {a} → {b}" for p, a, b in changes))
            model = new
        for op in others:
            if op.intent == "experiment":
                try:
                    values = json.loads(op.values_json or "[]")
                    spec = ExperimentSpec(name=f"chat: {request[:40]}", factors=[Factor(path=op.factor_path or "", values=values)])
                    validate_experiment(model, spec)
                except Exception as e:  # noqa: BLE001
                    return CommandResponse(plan, f"Experimento inválido: {e}", error=str(e))
                resp.experiment = self.run_experiment(project, spec, model)
                resp.message = f"Experimento ejecutado: {len(resp.experiment.scenarios)} escenarios."
            elif op.intent == "run":
                resp.simulation = self.run_simulation(project, model)
                resp.message = f"Simulación ejecutada (run {resp.simulation.run_id})."
            elif op.intent == "revert":
                vs = project.versions()
                cur = project.meta.current_version or 0
                prev = [v.version for v in vs if v.version < cur]
                if not prev:
                    return CommandResponse(plan, "No hay versión anterior.")
                if not confirm:
                    return CommandResponse(plan, f"¿Volver a v{prev[-1]}? (requiere confirmación)", needs_confirmation=True)
                project.checkout(prev[-1])
                resp.message, resp.new_version = f"Versión actual: v{prev[-1]}", prev[-1]
            elif op.intent == "compare_baseline":
                if project.meta.baseline_version is None:
                    return CommandResponse(plan, "No hay baseline definido.")
                base = project.load_version(project.meta.baseline_version)
                resp.changes = diff(base, model)
                resp.message = f"Diferencias con baseline v{project.meta.baseline_version}: {len(resp.changes)}"
            elif op.intent in ("explain_bottleneck", "explain_waiting"):
                res = self.run_simulation(project, model, trace=op.intent == "explain_waiting")
                resp.simulation = res
                codes = ("THEORETICAL_CONSTRAINT", "BOTTLENECK_CANDIDATE", "BLOCKING", "RESOURCE_CONTENTION", "RESOURCE_SATURATED", "QUEUE_BUILDUP")
                resp.findings = [f for f in res.findings if f.code in codes]
                resp.message = "Hechos calculados por el motor (no por la IA):"
        return resp

    # ------------------------------------------------------------- scenarios
    def compare_versions(self, project: Project, a: int, b: int) -> list[tuple[str, Any, Any]]:
        return diff(project.load_version(a), project.load_version(b))

    # ------------------------------------------------------------------ reports
    def generate_report(self, project: Project, run_id: str | None = None, experiment_id: str | None = None) -> dict[str, Path]:
        from ..reporting.report import build_markdown, markdown_to_html, results_csv

        model = project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        runs = project.runs(1)
        run = project.load_run(run_id) if run_id else (project.load_run(runs[0]["run_id"]) if runs else None)
        exp = project.load_experiment(experiment_id) if experiment_id else None
        md = build_markdown(model, self.validate_model(model), run, exp, project.name)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = project.root / "reports"
        out.mkdir(exist_ok=True)
        paths = {"markdown": out / f"report_{stamp}.md", "html": out / f"report_{stamp}.html"}
        paths["markdown"].write_text(md, encoding="utf-8")
        paths["html"].write_text(markdown_to_html(md, f"{project.name} — report"), encoding="utf-8")
        if run:
            paths["csv"] = out / f"kpis_{run.run_id}.csv"
            paths["csv"].write_text(results_csv(run), encoding="utf-8")
        project.log("system", "generate_report", result=str(paths["html"].name))
        return paths
