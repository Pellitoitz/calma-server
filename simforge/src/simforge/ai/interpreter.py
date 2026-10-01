"""Interpreters: natural language -> ProcessDraft / EditPlan.

Two implementations share one contract:
  * RuleBasedInterpreter (offline, deterministic, limited grammar) - also the fallback when the LLM fails
  * LLMInterpreter (any LLMProvider; privacy boundary via ai.context)

The LLM output is never trusted: it must validate against a strict schema AND pass semantic checks
(known component ids, existing step/resource references, existing model paths). Otherwise it is sent
back ONCE MORE with the errors (repair), at most `max_repairs` times; broken output is never used.
Every call is audited (input as sent, provider, model, prompt version, output, errors, repairs, tokens,
cost, latency). Secrets are never part of the prompt, so they cannot reach the audit log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from ..domain.isms import ISMSModel
from ..domain.paths import PathError, get_value
from ..library.registry import ComponentRegistry
from .context import Anonymizer, OutgoingContext, catalog_text, model_outline
from .prompts import EDIT_PROMPT_VERSION, EDIT_SYSTEM, PARSE_PROMPT_VERSION, PARSE_SYSTEM
from .provider import LLMError, LLMProvider, LLMUsage
from .rule_based import RuleBasedInterpreter
from .schemas import EditPlan, ProcessDraft


class Interpreter(Protocol):
    name: str

    def parse(self, text: str) -> ProcessDraft: ...
    def plan_edit(self, text: str, model: ISMSModel) -> EditPlan: ...


def validate_draft(draft: ProcessDraft, registry: ComponentRegistry) -> list[str]:
    """Semantic checks the schema cannot express."""
    errs: list[str] = []
    ids = [s.id for s in draft.steps]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errs.append(f"duplicate step id '{dup}'")
    res = {r.id: r for r in draft.resources}
    for s in draft.steps:
        if s.component != "buffer" and not registry.has(s.component):
            errs.append(f"step '{s.id}': component '{s.component}' is not in the catalog")
        for r in s.resources:
            if r not in res:
                errs.append(f"step '{s.id}': resource '{r}' is not declared in resources")
    for p in draft.policies:
        if p.resource not in res:
            errs.append(f"policy: resource '{p.resource}' is not declared")
        for sid in [*p.priority_order, *p.feeder_steps, *([p.protected_step] if p.protected_step else [])]:
            if sid not in ids:
                errs.append(f"policy on '{p.resource}': step '{sid}' does not exist")
    for loop in draft.carrier_loops:
        if loop.resource not in res or res[loop.resource].kind != "carrier":
            errs.append(f"carrier loop: '{loop.resource}' is not a declared carrier resource")
        for sid in (loop.seize_at, loop.release_at):
            if sid not in ids:
                errs.append(f"carrier loop: step '{sid}' does not exist")
    for e in draft.experiments:
        if not e.values:
            errs.append(f"experiment '{e.target}': no values")
    return errs


def validate_edit(plan: EditPlan, model: ISMSModel) -> list[str]:
    errs: list[str] = []
    for op in plan.operations:
        for name in ("value_json", "values_json", "expected_json"):
            raw = getattr(op, name)
            if raw is not None:
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    errs.append(f"{op.intent}: {name} is not valid JSON: {raw!r}")
        for path in (op.path, op.factor_path):
            if path:
                try:
                    get_value(model, path)
                except (KeyError, PathError, IndexError) as e:
                    errs.append(f"{op.intent}: path '{path}' does not exist in the model ({e})")
        if op.intent == "set" and (not op.path or op.value_json is None):
            errs.append("set: path and value_json are required")
        if op.intent == "experiment" and (not op.factor_path or not op.values_json):
            errs.append("experiment: factor_path and values_json are required")
    return errs


@dataclass
class CallAudit:
    purpose: str
    provider: str
    model: str
    prompt_version: str
    input_text: str  # exactly what was sent as user content (already anonymised)
    output_json: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    repairs: int = 0
    accepted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float | None = None
    latency_ms: float = 0.0


class LLMInterpreter:
    def __init__(self, provider: LLMProvider, registry: ComponentRegistry, anonymizer: Anonymizer | None = None,
                 on_usage: Callable[[LLMUsage, str], None] | None = None, on_audit: Callable[[CallAudit], None] | None = None,
                 max_repairs: int = 2):
        self.provider = provider
        self.registry = registry
        self.anon = anonymizer or Anonymizer()
        self.on_usage = on_usage
        self.on_audit = on_audit
        self.max_repairs = max_repairs
        self.name = f"llm:{provider.name}/{provider.model}"
        self.prompt_version = PARSE_PROMPT_VERSION
        self.last_context: OutgoingContext | None = None  # inspectable: exactly what left the machine
        self.last_audit: CallAudit | None = None

    def _call(self, ctx: OutgoingContext, schema, purpose: str, prompt_version: str, check: Callable[[Any], list[str]]):
        audit = CallAudit(purpose, self.provider.name, self.provider.model, prompt_version, ctx.user)
        t0 = time.perf_counter()
        user = ctx.user
        obj = None
        try:
            for attempt in range(self.max_repairs + 1):
                self.last_context = OutgoingContext(ctx.system, user)
                try:
                    raw, usage = self.provider.structured(ctx.system, user, schema)
                    if self.on_usage:
                        self.on_usage(usage, purpose)
                    audit.input_tokens += usage.input_tokens
                    audit.output_tokens += usage.output_tokens
                    if usage.est_cost_usd is not None:
                        audit.est_cost_usd = (audit.est_cost_usd or 0.0) + usage.est_cost_usd
                    out_json = raw.model_dump_json()
                    audit.output_json = out_json
                    errors = check(raw)
                except ValidationError as e:  # output did not match the schema
                    out_json, errors = None, [f"schema: {err['loc']}: {err['msg']}" for err in e.errors()][:20]
                if not errors:
                    obj = raw
                    audit.accepted = True
                    break
                audit.validation_errors += [f"attempt {attempt + 1}: {x}" for x in errors]
                if attempt == self.max_repairs:
                    break
                audit.repairs += 1
                user = (ctx.user + "\n\n---\nYour previous answer was rejected by the validator:\n- " + "\n- ".join(errors) +
                        ("\nPrevious answer:\n" + out_json if out_json else "") +
                        "\nReturn a corrected answer that fixes every error. Do not invent values.")
        finally:
            audit.latency_ms = (time.perf_counter() - t0) * 1000
            self.last_audit = audit
            if self.on_audit:
                self.on_audit(audit)
        if obj is None:
            raise LLMError(f"La salida del LLM no es válida tras {audit.repairs} reparaciones: " + "; ".join(audit.validation_errors[-3:]))
        restored = self.anon.restore(obj.model_dump_json())  # restore anonymised terms in the structured answer
        return schema.model_validate_json(restored)

    def parse(self, text: str) -> ProcessDraft:
        ctx = OutgoingContext(PARSE_SYSTEM.format(catalog=catalog_text(self.registry)), self.anon.anonymize(text))
        return self._call(ctx, ProcessDraft, "parse_process", PARSE_PROMPT_VERSION, lambda d: validate_draft(d, self.registry))

    def plan_edit(self, text: str, model: ISMSModel) -> EditPlan:
        ctx = OutgoingContext(EDIT_SYSTEM.format(outline=self.anon.anonymize(model_outline(model))), self.anon.anonymize(text))
        return self._call(ctx, EditPlan, "plan_edit", EDIT_PROMPT_VERSION, lambda p: validate_edit(p, model))


__all__ = ["CallAudit", "Interpreter", "LLMInterpreter", "RuleBasedInterpreter", "validate_draft", "validate_edit"]
