"""Application service: the internal API used by the CLI and the UI.

UI and CLI never touch the engine, the database or the LLM directly; they call
these functions. (A FastAPI layer can wrap this class 1:1 later.)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import time

from ..ai.compiler import ParseOutcome, compile_draft
from ..ai.edits import chat_provenance, correction_reason, friendly, is_correction, resolve_edit, resolve_factor_path
from ..ai.context import Anonymizer
from ..ai.interpreter import CallAudit, Interpreter, LLMInterpreter, RuleBasedInterpreter
from ..ai.provider import LLMError, LLMProvider, LLMUsage, provider_from_env
from ..ai.schemas import EditPlan, ProcessDraft
from ..analytics.diagnostics import Finding
from ..domain.isms import Approval, ExperimentSpec, Factor, ISMSModel
from ..domain.paths import diff, get_value, set_value
from ..experiments.runner import ExperimentResult, SimulationResult, run_experiment, run_simulation, validate_experiment
from ..library.registry import ComponentRegistry
from ..persistence.project import Project, Workspace
from ..validation.semantics import verify_model as verify
from ..validation.verifier import VerificationReport


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
    generation_ms: float = 0.0


class ApprovalRequired(RuntimeError):
    """An AI-generated model must be reviewed and approved by the engineer before its first run."""


def data_linked_paths(model: ISMSModel) -> list[str]:
    """Paths of values whose provenance links to an imported dataset."""
    out: list[str] = []

    def walk(x: Any, path: str) -> None:
        if isinstance(x, dict):
            prov = x.get("provenance")
            if isinstance(prov, dict) and prov.get("data"):
                out.append(path)
            for k, v in x.items():
                if k != "provenance":
                    walk(v, f"{path}.{k}" if path else k)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}.{v['id'] if isinstance(v, dict) and 'id' in v else i}")
    walk(model.model_dump(mode="json", exclude={"approval": True, "meta": True}), "")
    return out


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

        def log_audit(a: CallAudit) -> None:
            if project:
                project.audit(a.purpose, a.provider, a.model, a.prompt_version, a.input_text, a.output_json, a.validation_errors,
                              a.repairs, a.accepted, a.input_tokens, a.output_tokens, a.est_cost_usd, a.latency_ms)

        return LLMInterpreter(self.provider, self.registry, anon, log_usage, log_audit)

    def data(self, project: Project):
        """Data import & distribution fitting on a project (offline, no LLM)."""
        from ..data.service import DataService
        return DataService(project, self.registry)

    # ----------------------------------------------------------------- projects
    def create_project(self, name: str, description: str = "") -> Project:
        return self.workspace.create_project(name, description)

    def list_projects(self):
        return self.workspace.list_projects()

    def open_project(self, slug: str) -> Project:
        return self.workspace.open_project(slug)

    # ------------------------------------------------------------------- model
    def parse_process(self, project: Project, text: str, prototype: bool = False) -> ParseResponse:
        """Natural language -> interpretation (AI or rules) -> library matching -> parameters -> ISMS -> verification.
        The result is a new model VERSION (the chat is never the model)."""
        interp = self.interpreter(project)
        t0 = time.perf_counter()
        try:
            draft = interp.parse(text)
        except LLMError as e:  # fallback without AI: the deterministic offline interpreter (stated, never silent)
            project.log("system", "llm_fallback", request=text, result=str(e))
            interp = RuleBasedInterpreter(self.registry)
            interp.name = f"offline-rules (fallback: {str(e)[:80]})"
            draft = interp.parse(text)
        if isinstance(interp, RuleBasedInterpreter):
            project.audit("parse_process", "offline-rules", "-", interp.prompt_version, text, draft.model_dump_json(), [], 0, True)
        return self._build(project, text, draft, interp.name, getattr(interp, "prompt_version", None), {}, prototype, t0)

    def _build(self, project: Project, text: str, draft: ProcessDraft, interpreter: str, prompt_version: str | None,
               answers: dict[str, Any], prototype: bool, t0: float) -> ParseResponse:
        for key, val in answers.items():  # structural answers change the interpretation, never the engine
            if key.startswith("return_mode:"):
                for loop in draft.carrier_loops:
                    if loop.resource == key.split(":", 1)[1]:
                        loop.return_mode = val
        outcome = compile_draft(draft, self.registry, text, prototype=prototype,
                                generated_by={"interpreter": interpreter, "prompt_version": prompt_version})
        model = outcome.model
        for key, val in answers.items():
            if key.startswith("param:") and any(p.id == key[6:] for p in model.parameters):
                model = set_value(model, f"parameters.{key[6:]}.value", val)
                model = set_value(model, f"parameters.{key[6:]}.provenance", chat_provenance(f"answer: {val}", "answer"))
        prev = project.current_model()
        if prev is not None and getattr(prev, "availability", None) is not None:
            # the compiler (frozen) knows nothing about calendars: never drop the engineer's calendars when rebuilding
            from ..domain.isms_ext import as_sim_model
            model = as_sim_model(model).model_copy(update={"availability": prev.availability})
            project.log("system", "availability_carried_over",
                        result=f"calendars of v{project.meta.current_version} kept in the rebuilt model (references re-verified)")
        if prev is not None and getattr(prev, "production", None) is not None:
            # nor about products/setups (engine >= 0.7.0): kept, and re-verified against the rebuilt structure
            from ..domain.isms_ext import as_sim_model
            model = as_sim_model(model).model_copy(update={"production": prev.production})
            project.log("system", "production_carried_over",
                        result=f"products/setups of v{project.meta.current_version} kept in the rebuilt model (references re-verified)")
        if prev is not None and getattr(prev, "maintenance", None) is not None:
            from ..domain.isms_ext import as_sim_model
            model = as_sim_model(model).model_copy(update={"maintenance": prev.maintenance})
            project.log("system", "maintenance_carried_over",
                        result=f"maintenance of v{project.meta.current_version} kept in the rebuilt model (references re-verified)")
        if prev is not None and getattr(prev, "economics", None) is not None:
            from ..domain.isms_ext import as_sim_model
            model = as_sim_model(model).model_copy(update={"economics": prev.economics})
            project.log("system", "economics_carried_over",
                        result=f"economic assumptions of v{project.meta.current_version} kept in the rebuilt model")
        outcome.model = model
        gen_ms = (time.perf_counter() - t0) * 1000
        report, _ = verify(model, self.registry)
        v = project.save_version(model, message=f"generated from description ({interpreter})", author="ai")
        project.save_interpretation(text, draft.model_dump_json(), interpreter, prompt_version, gen_ms, v, answers)
        project.log("ai", "parse_process", request=text, interpretation=draft.model_dump_json(),
                    change={"matches": [m.__dict__ for m in outcome.matches], "reuse_ratio": outcome.reuse_ratio},
                    result=report.summary())
        project.record_metric("reuse_ratio", outcome.reuse_ratio)
        project.record_metric("custom_logic_count", outcome.custom_count)
        project.record_metric("ai_questions", len(outcome.questions()))
        project.record_metric("ai_generation_s", gen_ms / 1000)
        return ParseResponse(outcome, report, v, interpreter, gen_ms)

    def answer_questions(self, project: Project, answers: dict[str, Any], prototype: bool = False) -> ParseResponse:
        """Engineer answers -> merged with previous answers -> deterministic recompilation of the stored interpretation.
        keys: 'param:<id>' (value) or 'return_mode:<carrier>' (immediate | transport)."""
        last = project.last_interpretation()
        if last is None:
            raise ValueError("No hay ninguna descripción interpretada en este proyecto.")
        merged = {**json.loads(last["answers_json"] or "{}"), **answers}
        draft = ProcessDraft.model_validate_json(last["draft_json"])
        project.log("user", "answer_questions", request=json.dumps(answers, default=str))
        return self._build(project, last["text"], draft, last["interpreter"], last["prompt_version"], merged, prototype,
                           time.perf_counter())

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
        scenario = project.scenario_of(project.meta.current_version)
        v = project.save_version(approved, message=f"engineer approval by {by}", author=by)
        if scenario is not None:  # the approved copy becomes the head of the same scenario (lineage: parent = old head)
            project.assign_scenario(scenario, v)
        project.log("user", "approve_model", result=f"v{v} approved by {by}" + (f" (scenario '{scenario}')" if scenario else ""))
        if project.metric("time_to_engineer_approval_s") is None:
            first = project.versions()[0].created_at
            delta = datetime.now(timezone.utc) - datetime.fromisoformat(first)
            project.record_metric("time_to_engineer_approval_s", delta.total_seconds())
        last = project.last_interpretation()
        if last and project.metric("engineer_review_s") is None:
            gen_at = datetime.fromisoformat(last["created_at"])
            project.record_metric("engineer_review_s", (datetime.now(timezone.utc) - gen_at).total_seconds(),
                                  "wall clock from last AI generation to approval (includes corrections)")
        return v

    def decide_custom_rule(self, project: Project, candidate_id: str, decision: str, by: str, note: str = "") -> int:
        """Engineer decision on a CustomRuleCandidate: 'deferred' (run WITHOUT the rule, reported as not modelled)
        or 'rejected'. Implementing it is a library change (test + validate + approve), never done automatically."""
        if decision not in ("deferred", "rejected"):
            raise ValueError("Decisión no válida: usa 'deferred' (ejecutar sin la regla) o 'rejected'.")
        model = project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        if not any(c.id == candidate_id for c in model.custom_rule_candidates):
            raise KeyError(f"No existe la regla candidata '{candidate_id}'.")
        cands = [c.model_copy(update={"status": decision}) if c.id == candidate_id else c for c in model.custom_rule_candidates]
        new = model.model_copy(update={"custom_rule_candidates": cands})
        v = project.save_version(new, message=f"custom rule {candidate_id}: {decision} by {by}" + (f" ({note})" if note else ""), author=by)
        project.log("user", "decide_custom_rule", result=f"v{v}: {candidate_id} -> {decision}")
        return v

    def library_improvement_candidates(self, min_occurrences: int = 2) -> list[dict[str, Any]]:
        """Repeated engineer corrections and repeated custom rules across ALL projects of the workspace.
        Reported as CANDIDATE_FOR_LIBRARY_IMPROVEMENT; the library is NEVER modified automatically."""
        corr: dict[tuple[str, str], list[dict]] = {}
        rules: dict[str, list[dict]] = {}
        for meta in self.workspace.list_projects():
            proj = self.open_project(meta.slug)
            try:
                for c in proj.corrections():
                    role = re.sub(r"_\d+", "", c["parameter"]) if not c["component"] else c["parameter"].rsplit("_", 1)[-1]
                    corr.setdefault((c["component"] or "-", role), []).append({**c, "project": meta.name})
                model = proj.current_model()
                for cand in (model.custom_rule_candidates if model else []):
                    key = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", cand.description.lower().translate(
                        str.maketrans("áéíóúüñ", "aeiouun")))).strip()
                    rules.setdefault(key, []).append({"project": meta.name, "status": cand.status, "description": cand.description})
            finally:
                proj.close()
        out: list[dict[str, Any]] = []
        for (comp, role), items in sorted(corr.items()):
            if len(items) >= min_occurrences:
                out.append({"status": "CANDIDATE_FOR_LIBRARY_IMPROVEMENT", "kind": "parameter_correction", "component": comp,
                            "parameter": role, "occurrences": len(items), "projects": sorted({i["project"] for i in items}),
                            "ai_values": [i["ai_value"] for i in items], "engineer_values": [i["engineer_value"] for i in items],
                            "reasons": [i["reason"] for i in items if i["reason"]],
                            "suggestion": f"Revisar el default / la interpretación de '{role}' en '{comp}' (corregido {len(items)} veces)."})
        for key, items in sorted(rules.items()):
            if len(items) >= min_occurrences:
                out.append({"status": "CANDIDATE_FOR_LIBRARY_IMPROVEMENT", "kind": "custom_rule", "component": None,
                            "parameter": None, "occurrences": len(items), "projects": sorted({i["project"] for i in items}),
                            "description": items[0]["description"],
                            "suggestion": "Regla pedida repetidamente: candidata a componente de biblioteca "
                                          "(implementar + test + validar + aprobación del ingeniero)."})
        return out

    def compare_models(self, a: ISMSModel | str, b: ISMSModel | str, run: bool = True, rel_tol: float = 1e-9):
        """compare_model_specs(A, B) and, when they are structurally equivalent, run both (same settings) and compare KPIs.
        A/B: models or their JSON/YAML text. Verification runs: not stored in any project."""
        from ..validation.equivalence import _load, compare_model_specs, compare_results

        spec = compare_model_specs(a, b, self.registry)
        results = None
        if run and spec.structurally_equivalent:
            ma, mb = _load(a)[0], _load(b)[0]
            results = compare_results(run_simulation(ma, self.registry), run_simulation(mb, self.registry), spec, rel_tol=rel_tol)
        return spec, results

    def approval_pending(self, project: Project, model: ISMSModel) -> bool:
        """AI-generated models need ONE engineer approval before their first run. Later edited versions may run
        (they are reported as derived, not approved). A model with values derived from imported data (provenance.data)
        must be approved in its exact current content: applying data is a semantic change."""
        if model.is_approved:
            return False
        if data_linked_paths(model):
            return True
        if model.meta.origin != "ai_generated":
            return False
        return not any(project.load_version(v.version).is_approved for v in project.versions() if v.author not in ("ai",))

    def _check_approval(self, project: Project, model: ISMSModel) -> None:
        if not self.approval_pending(project, model):
            return
        rep = self.validate_model(model)
        if data_linked_paths(model):
            raise ApprovalRequired("El modelo contiene parámetros derivados de datos importados "
                                   f"({', '.join(data_linked_paths(model))}) y esta versión no está aprobada: revisa los cambios "
                                   f"y apruébala antes de ejecutar (estado: {rep.readiness.value}).")
        raise ApprovalRequired("Modelo generado por IA: revisa el flujo, componentes, parámetros y supuestos y apruébalo "
                               f"antes de la primera ejecución (estado: {rep.readiness.value}).")

    # --------------------------------------------------------------- simulation
    def run_simulation(self, project: Project, model: ISMSModel | None = None, replications: int | None = None,
                       trace: bool | None = None, keep_records: bool = False) -> SimulationResult:
        model = model or project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        self._check_approval(project, model)
        version = project.version_of(model)  # the version ACTUALLY executed (None = unsaved model), never "current"
        try:
            res = run_simulation(model, self.registry, replications=replications, trace=trace, cache=project,
                                 keep_records=keep_records)
        except KeyboardInterrupt:
            project.log("system", "run_interrupted", result=f"model v{version}: interrupted; no run stored")
            raise
        except Exception as e:  # a failed run is never stored as a result; the error is kept for diagnosis
            project.log("system", "run_failed", result=f"model v{version}: {type(e).__name__}: {e}"[:2000])
            raise
        project.save_run(res, version)
        project.log("system", "run_simulation", result=f"run {res.run_id} (model v{version}): "
                    f"TH={res.kpis.mean('throughput_per_hour'):.2f}/h")
        return res

    # --------------------------------------------------------------- economics (>= 0.9.0, post-run, no DES)
    def run_model_of(self, project: Project, run_id: str) -> ISMSModel:
        row = project.db.execute("SELECT model_version, model_hash FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"No existe la ejecución '{run_id}'.")
        if row[0] is None:
            raise ValueError(f"La ejecución '{run_id}' es de un modelo no guardado como versión: su modelo no se puede "
                             "recuperar del proyecto (nunca se sustituye por la versión actual).")
        model = project.load_version(row[0])
        if model.content_hash() != row[1]:
            raise ValueError(f"La versión v{row[0]} no coincide con el hash físico del run '{run_id}'.")
        return model

    def evaluate_economics(self, project: Project, run_id: str, assumptions=None):
        """Evaluate a STORED physical run with economic assumptions (default: those of the current model version).
        No simulation is executed."""
        from ..economics import evaluate_run
        run = project.load_run(run_id)
        model = self.run_model_of(project, run_id)
        if assumptions is None:
            cur = project.current_model()
            assumptions = getattr(cur, "economics", None) or getattr(model, "economics", None)
        ev = evaluate_run(run, model, assumptions, self.registry)
        project.save_evaluation(ev, assumptions)
        project.log("system", "evaluate_economics", result=f"evaluation {ev.evaluation_id} of run {run_id}: {ev.status}")
        return ev

    def compare_economics(self, project: Project, baseline_id: str, alternative_id: str):
        from ..economics import compare_evaluations
        eb, ea = project.load_evaluation(baseline_id), project.load_evaluation(alternative_id)
        return compare_evaluations(eb, ea, self.run_model_of(project, eb.run_id), self.run_model_of(project, ea.run_id))

    def run_experiment(self, project: Project, spec: ExperimentSpec, model: ISMSModel | None = None,
                       progress: Callable[[int, int], None] | None = None) -> ExperimentResult:
        model = model or project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        self._check_approval(project, model)
        res = run_experiment(model, spec, self.registry, cache=project, progress=progress)
        project.save_experiment(res, project.version_of(model))
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
        try:
            plan = interp.plan_edit(text, model)
        except LLMError as e:
            if not isinstance(interp, LLMInterpreter):
                raise
            # the offline planner still handles the common requests; invalid LLM output is never applied
            project.log("system", "llm_fallback", request=text, result=str(e))
            interp = RuleBasedInterpreter(self.registry)
            plan = interp.plan_edit(text, model)
            if not plan.operations:
                return CommandResponse(plan, f"La IA no produjo un cambio válido ({e}). {plan.question or ''}", error=str(e))
            resp = self.apply_plan(project, plan, text, "offline-rules (fallback)", confirm)
            resp.message = f"[Salida de la IA rechazada por el validador; interpretado sin IA] {resp.message}"
            return resp
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
                touched: list[str] = []
                for op in sets:
                    value = json.loads(op.value_json or "null")
                    path, value = resolve_edit(new, op.path or "", value)
                    if op.expected_json is not None and not confirm:
                        expected = json.loads(op.expected_json)
                        current = get_value(new, path)
                        if current is not None and expected is not None and float(current) != float(expected):
                            return CommandResponse(plan, f"'{path}' vale {current}, no {expected}. ¿Lo cambio igualmente a {value}? "
                                                         "(requiere confirmación)", needs_confirmation=True)
                    if path.startswith("parameters.") and path.endswith(".value"):
                        touched.append(path.split(".")[1])
                        new = set_value(new, path, value)
                        new = set_value(new, path.rsplit(".", 1)[0] + ".provenance", chat_provenance(request))
                        continue
                    if isinstance(value, dict) and "dist" in value and "provenance" not in value:
                        value["provenance"] = chat_provenance(request)
                    new = set_value(new, path, value)
            except Exception as e:  # noqa: BLE001
                return CommandResponse(plan, f"No se pudo aplicar el cambio: {e}", error=str(e))
            changes = diff(model, new, ignore_provenance=True)
            if not changes:
                return CommandResponse(plan, "Sin cambios: el modelo ya tiene esos valores.")
            important = len(changes) > 2 or model.is_approved or any(p.startswith("resources.") and n in (0, None) for p, _, n in changes)
            if important and not confirm:
                return CommandResponse(plan, "Cambio importante: requiere confirmación." +
                                       (" El modelo está aprobado; el cambio invalidará la aprobación." if model.is_approved else ""),
                                       changes=changes, needs_confirmation=True)
            v = project.save_version(new, message=f"chat: {request[:80]}", author="ai")
            project.log("ai", "edit", request=request, interpretation=plan.model_dump_json(), change=[list(c) for c in changes], result=f"v{v}")
            if model.meta.origin == "ai_generated":
                for pid in touched:
                    if is_correction(model, pid, request):
                        before = next(p.value for p in model.parameters if p.id == pid)
                        after = next(p.value for p in new.parameters if p.id == pid)
                        if before != after:
                            comp = next((n.component for n in new.nodes if f"${pid}" in n.model_dump_json()), None)
                            project.record_correction(pid, comp, before, after, correction_reason(request), request, v)
            resp.changes, resp.new_version = changes, v
            resp.message = "Modelo actualizado (v%d): %s" % (v, "; ".join(
                f"{c['parameter']} ({c['used_in']}): {c['before']} → {c['after']}" for c in friendly(new, changes)))
            model = new
        for op in others:
            if op.intent == "experiment":
                try:
                    values = json.loads(op.values_json or "[]")
                    fpath = resolve_factor_path(model, op.factor_path or "")
                    spec = ExperimentSpec(name=f"chat: {request[:40]}", factors=[Factor(path=fpath, values=values)])
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

    @staticmethod
    def _apply_changes(model: ISMSModel, changes: dict[str, Any]) -> ISMSModel:
        new = model
        for path, value in changes.items():
            new = set_value(new, path, value)  # validated by the domain; unknown paths / invalid values raise
        return new

    def clone_scenario(self, project: Project, name: str, changes: dict[str, Any] | None = None,
                       from_version: int | None = None, message: str = "", by: str = "engineer") -> int:
        """Baseline -> clone -> modify (1.1-A). A new immutable version derived from `from_version` (default: the
        baseline), with lineage parent = that version, labelled `scenario:<name>`; it becomes current. Approval is
        never copied as valid: it stays bound to the content hash, so any real change leaves the clone unapproved.
        The baseline version is not touched."""
        from ..persistence.project import ProjectError
        name = (name or "").strip()
        if not name:
            raise ProjectError("El escenario necesita un nombre.")
        if name in project.meta.scenarios:
            raise ProjectError(f"El escenario '{name}' ya existe (v{project.meta.scenarios[name]}): modifícalo o usa otro nombre.")
        if project.meta.baseline_version is None:
            raise ProjectError("Define primero un baseline: los escenarios se derivan del baseline.")
        src = project.meta.baseline_version if from_version is None else from_version
        base = project.load_version(src)
        new = self._apply_changes(base, changes or {})
        d = diff(base, new, ignore_provenance=True)
        v = project.create_scenario(name, new, message or f"scenario {name} from v{src}: " +
                                    ("; ".join(f"{p}={b}" for p, _, b in d)[:200] or "clone without changes"), parent=src, author=by)
        project.log("user", "clone_scenario", result=f"scenario '{name}' = v{v} (from v{src}, {len(d)} change(s))",
                    change=[list(c) for c in d] or None)
        return v

    def modify_scenario(self, project: Project, name: str, changes: dict[str, Any], message: str = "",
                        by: str = "engineer") -> int:
        """New version of an existing scenario (parent = its current head); the scenario name moves to it."""
        from ..persistence.project import ProjectError
        if name not in project.meta.scenarios:
            raise ProjectError(f"No existe el escenario '{name}'.")
        head = project.meta.scenarios[name]
        model = project.load_version(head)
        new = self._apply_changes(model, changes)
        d = diff(model, new, ignore_provenance=True)
        if not d:
            raise ProjectError("Sin cambios: el escenario ya tiene esos valores.")
        v = project.save_version(new, message or f"scenario {name}: " + "; ".join(f"{p}={b}" for p, _, b in d)[:200],
                                 author=by, label=f"scenario:{name}", parent=head)
        project.assign_scenario(name, v)
        project.log("user", "modify_scenario", result=f"scenario '{name}' = v{v} (from v{head})", change=[list(c) for c in d])
        return v

    def run_identity(self, project: Project, run_id: str):
        from ..analytics.run_comparison import identity
        run = project.load_run(run_id)
        row = project.db.execute("SELECT model_version FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        ver = row[0] if row else None
        base = project.meta.baseline_version
        return run, identity(run, ver, project.scenario_of(ver), (ver == base) if ver is not None and base is not None else None)

    def compare_runs(self, project: Project, baseline_run_id: str, alternative_run_id: str, metrics: list[str] | None = None):
        """Physical comparison of two STORED runs (1.1-A). Computed on demand, never stored, never simulates."""
        from ..analytics.run_comparison import compare_physical_runs
        b, bid = self.run_identity(project, baseline_run_id)
        a, aid = self.run_identity(project, alternative_run_id)

        def model(i):
            try:
                return self.run_model_of(project, i.run_id) if i.model_version is not None else None
            except ValueError:
                return None
        return compare_physical_runs(b, a, metrics=metrics, base_model=model(bid), alt_model=model(aid), registry=self.registry,
                                     baseline_identity=bid, alternative_identity=aid)

    def _stored_model_of(self, project: Project, run_id: str):
        try:
            return self.run_model_of(project, run_id)
        except ValueError:
            return None  # run of an unsaved model (or hash mismatch): no model-based ordering / overlay

    def results_workbench(self, project: Project, run_id: str):
        """1.1-C results workbench of a STORED run (never simulates)."""
        from ..analytics.workbench import build_workbench
        run, ident = self.run_identity(project, run_id)
        return build_workbench(run, ident, self._stored_model_of(project, run_id))

    def graph_overlay(self, project: Project, run_id: str, metric: str):
        """Stored node KPI on the run's own model version (None when that model is not available)."""
        from ..analytics.workbench import graph_overlay
        model = self._stored_model_of(project, run_id)
        return (graph_overlay(project.load_run(run_id), model, metric), model) if model is not None else (None, None)

    def experiment_deltas(self, project: Project, experiment_id: str, reference_index: int = 0, metrics: list[str] | None = None):
        from ..analytics.run_comparison import experiment_deltas
        return experiment_deltas(project.load_experiment(experiment_id), reference_index, metrics)

    # ------------------------------------------------------------------ reports
    def generate_report(self, project: Project, run_id: str | None = None, experiment_id: str | None = None) -> dict[str, Path]:
        from ..reporting.report import build_markdown, markdown_to_html, results_csv

        runs = project.runs(1)
        run = project.load_run(run_id) if run_id else (project.load_run(runs[0]["run_id"]) if runs else None)
        # the report describes the model OF THE RUN (never the current version next to another version's results)
        model = self.run_model_of(project, run.run_id) if run else project.current_model()
        if model is None:
            raise ValueError("El proyecto no tiene modelo.")
        exp = project.load_experiment(experiment_id) if experiment_id else None
        evals = [project.load_evaluation(e["evaluation_id"]) for e in project.evaluations(run.run_id)] if run else []
        md = build_markdown(model, self.validate_model(model), run, exp, project.name, evaluations=evals)
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
