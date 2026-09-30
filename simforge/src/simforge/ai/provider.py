"""LLM provider abstraction. The rest of SimForge only sees `LLMProvider`.

Providers only do one thing: return a validated Pydantic object for a
(system, user) prompt. No tool execution, no code execution, no results.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (input, output) - Anthropic first-party list prices, cached 2026-09.
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class LLMUsage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    sent_chars: int = 0

    @property
    def est_cost_usd(self) -> float | None:
        p = PRICING.get(self.model)
        if not p:
            return None
        return (self.input_tokens * p[0] + self.output_tokens * p[1]) / 1e6


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def structured(self, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]: ...


@dataclass
class MockLLMProvider:
    """Deterministic provider for tests. `responder(user_text, schema) -> dict`.
    Every prompt is recorded in `calls` so tests can assert what would be sent."""

    responder: Callable[[str, type[BaseModel]], dict[str, Any]]
    name: str = "mock"
    model: str = "mock-1"
    calls: list[dict[str, str]] = field(default_factory=list)

    def structured(self, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        self.calls.append({"system": system, "user": user, "schema": schema.__name__})
        obj = schema.model_validate(self.responder(user, schema))
        return obj, LLMUsage(self.name, self.model, len(system + user) // 4, len(json.dumps(obj.model_dump())) // 4,
                             len(system) + len(user))


class AnthropicProvider:
    """Claude via the official SDK, using structured outputs (`messages.parse`).

    Forced tool use is not used: current models reject forced `tool_choice`,
    and structured outputs give schema-valid JSON directly.
    """

    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None, max_tokens: int = 16000):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise LLMError("Instala el extra 'llm': pip install -e '.[llm]'") from e
        import anthropic

        self.model = model or os.environ.get("SIMFORGE_LLM_MODEL", "claude-opus-5-5")
        self.max_tokens = max_tokens
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def structured(self, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        a = self._anthropic
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except a.AuthenticationError as e:
            raise LLMError("API key de Anthropic inválida o ausente (ANTHROPIC_API_KEY).") from e
        except a.RateLimitError as e:
            raise LLMError("Límite de peticiones alcanzado; reintenta en unos segundos.") from e
        except a.APIStatusError as e:
            raise LLMError(f"Error de la API ({e.status_code}): {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Sin conexión con la API. La simulación sigue funcionando offline.") from e
        if resp.stop_reason == "refusal":
            raise LLMError("El modelo rechazó la petición (refusal). Reformula la descripción.")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise LLMError("La respuesta del modelo quedó incompleta; intenta con una descripción más corta.")
        usage = LLMUsage(self.name, self.model, resp.usage.input_tokens, resp.usage.output_tokens, len(system) + len(user))
        return resp.parsed_output, usage


def provider_from_env() -> LLMProvider | None:
    """Real provider only if a key is configured; otherwise None (offline rule-based interpreter is used)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider()
    return None
