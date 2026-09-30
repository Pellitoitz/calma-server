"""Privacy boundary: the ONLY place that decides what leaves the machine.

Rules:
  * Only the user's request text, the component catalog (our own IP-free
    summaries) and, for edits, a compact model outline are sent.
  * Never attachments, files, run data, history, or client metadata.
  * `sensitive_terms` (customer names, product refs, people...) are replaced
    by placeholders before sending and restored in the answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..domain.isms import ISMSModel
from ..library.registry import ComponentRegistry


@dataclass
class Anonymizer:
    terms: dict[str, str] = field(default_factory=dict)  # real -> placeholder

    def anonymize(self, text: str) -> str:
        for real in sorted(self.terms, key=len, reverse=True):
            text = re.sub(re.escape(real), self.terms[real], text, flags=re.IGNORECASE)
        return text

    def restore(self, text: str) -> str:
        for real, ph in self.terms.items():
            text = text.replace(ph, real)
        return text

    @classmethod
    def with_defaults(cls, terms: dict[str, str]) -> "Anonymizer":
        return cls({k: v for k, v in terms.items() if k.strip()})


def catalog_text(registry: ComponentRegistry) -> str:
    return "\n".join(f"- {c['id']} ({c['behavior']}): {c['summary']}" for c in registry.catalog())


def model_outline(model: ISMSModel) -> str:
    """Compact outline for edit commands: structure and parameters, no notes/provenance/meta."""
    nodes = []
    for n in model.nodes:
        entry = {"id": n.id, "name": n.name, "component": n.component, "priority": n.priority}
        if n.params:
            entry["params"] = n.params
        if n.seize:
            entry["seize"] = [s.resource for s in n.seize]
        if n.release:
            entry["release"] = n.release
        nodes.append(entry)
    outline = {
        "horizon": model.simulation.horizon.model_dump(exclude_none=True, exclude={"provenance"}),
        "replications": model.simulation.replications,
        "resources": [{"id": r.id, "kind": r.kind.value, "quantity": r.quantity, "dispatch": r.dispatch.value} for r in model.resources],
        "nodes": nodes,
        "edges": [[e.source, e.target] for e in model.edges],
    }
    return json.dumps(outline, ensure_ascii=False, default=str)


@dataclass
class OutgoingContext:
    system: str
    user: str

    @property
    def chars(self) -> int:
        return len(self.system) + len(self.user)
