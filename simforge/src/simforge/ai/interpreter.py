"""Interpreters: natural language -> ProcessDraft / EditPlan.

Two implementations share one contract:
  * RuleBasedInterpreter (offline, deterministic, limited grammar)
  * LLMInterpreter (any LLMProvider; privacy boundary via ai.context)
"""

from __future__ import annotations

from typing import Callable, Protocol

from ..domain.isms import ISMSModel
from ..library.registry import ComponentRegistry
from .context import Anonymizer, OutgoingContext, catalog_text, model_outline
from .prompts import EDIT_SYSTEM, PARSE_SYSTEM
from .provider import LLMProvider, LLMUsage
from .rule_based import RuleBasedInterpreter
from .schemas import EditPlan, ProcessDraft


class Interpreter(Protocol):
    name: str

    def parse(self, text: str) -> ProcessDraft: ...
    def plan_edit(self, text: str, model: ISMSModel) -> EditPlan: ...


class LLMInterpreter:
    def __init__(self, provider: LLMProvider, registry: ComponentRegistry, anonymizer: Anonymizer | None = None,
                 on_usage: Callable[[LLMUsage, str], None] | None = None):
        self.provider = provider
        self.registry = registry
        self.anon = anonymizer or Anonymizer()
        self.on_usage = on_usage
        self.name = f"llm:{provider.name}/{provider.model}"
        self.last_context: OutgoingContext | None = None  # inspectable: exactly what left the machine

    def _call(self, ctx: OutgoingContext, schema, purpose: str):
        self.last_context = ctx
        obj, usage = self.provider.structured(ctx.system, ctx.user, schema)
        if self.on_usage:
            self.on_usage(usage, purpose)
        # restore anonymised terms in the structured answer
        restored = self.anon.restore(obj.model_dump_json())
        return schema.model_validate_json(restored)

    def parse(self, text: str) -> ProcessDraft:
        ctx = OutgoingContext(PARSE_SYSTEM.format(catalog=catalog_text(self.registry)), self.anon.anonymize(text))
        return self._call(ctx, ProcessDraft, "parse_process")

    def plan_edit(self, text: str, model: ISMSModel) -> EditPlan:
        ctx = OutgoingContext(EDIT_SYSTEM.format(outline=self.anon.anonymize(model_outline(model))), self.anon.anonymize(text))
        return self._call(ctx, EditPlan, "plan_edit")


__all__ = ["Interpreter", "LLMInterpreter", "RuleBasedInterpreter"]
