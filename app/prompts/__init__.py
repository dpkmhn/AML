"""Versioned prompts: app/prompts/<name>_v<N>.md, never edited in place."""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).resolve().parent


def prompt_id(name: str, version: int) -> str:
    return f"{name}_v{version}"


def load_prompt(name: str, version: int) -> str:
    return (PROMPTS / f"{prompt_id(name, version)}.md").read_text(encoding="utf-8")
