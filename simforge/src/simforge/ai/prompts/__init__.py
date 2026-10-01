"""Versioned prompts. Each prompt is a file `<name>_v<N>.txt`; the version used is recorded in every
generated model (meta.generated_by.prompt_version) and in the AI audit log. Never edit a released
version in place: add `<name>_v<N+1>.txt` and switch the constant below."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

PARSE_PROMPT_VERSION = "process_parser_v1"
EDIT_PROMPT_VERSION = "edit_planner_v1"


@lru_cache
def load_prompt(version: str) -> str:
    path = PROMPTS_DIR / f"{version}.txt"
    if not path.exists():
        raise KeyError(f"Prompt '{version}' no existe ({', '.join(available())}).")
    return path.read_text(encoding="utf-8")


def available() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.txt"))


PARSE_SYSTEM = load_prompt(PARSE_PROMPT_VERSION)
EDIT_SYSTEM = load_prompt(EDIT_PROMPT_VERSION)
