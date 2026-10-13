"""@audited(step): time a graph node and write one audit_log row per run of it.

LLM nodes call record_usage() inside the node; the decorator picks the model and token counts
up from there, so non-LLM nodes need no extra code. A node that pauses for a human (an
interrupt) writes nothing; its row is written when it runs to the end on resume.
"""

from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from langgraph.errors import GraphInterrupt
from pydantic import BaseModel
from sqlalchemy import text

from app.db import session

Node = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Usage:
    model: str | None = None
    prompt_version: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


_usage: ContextVar[Usage | None] = ContextVar("audit_usage", default=None)


def record_usage(model: str, prompt_version: str | int, tokens_in: int, tokens_out: int) -> None:
    """Called by an LLM node; adds to the totals for the node being audited."""
    u = _usage.get()
    if u is not None:
        u.model, u.prompt_version = model, str(prompt_version)
        u.tokens_in += tokens_in
        u.tokens_out += tokens_out


def jsonable(value: Any) -> Any:
    """Pydantic models, dates and lists of them as plain JSON values."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return json.loads(json.dumps(value, default=str))


_INSERT = text("""
INSERT INTO audit_log (case_id, step, model, prompt_version, input, output,
                       tokens_in, tokens_out, latency_ms)
VALUES (:case_id, :step, :model, :prompt_version, CAST(:input AS jsonb), CAST(:output AS jsonb),
        :tokens_in, :tokens_out, :latency_ms)
""")


def write_row(row: dict[str, Any]) -> None:
    with session("rw") as s:
        s.execute(_INSERT, row)


def read_trail(case_id: str) -> list[dict[str, Any]]:
    """Every audit row of a case, in order."""
    with session("rw") as s:
        rows = s.execute(text("SELECT id, step, model, prompt_version, output, tokens_in, "
                              "tokens_out, latency_ms, created_at FROM audit_log "
                              "WHERE case_id = :c ORDER BY id"), {"c": case_id}).mappings()
        return [dict(r) for r in rows]


def audited(step: str) -> Callable[[Node], Node]:
    def wrap(fn: Node) -> Node:
        @functools.wraps(fn)
        def node(state: dict[str, Any]) -> dict[str, Any]:
            usage = Usage()
            token = _usage.set(usage)
            t0 = time.perf_counter()
            try:
                out = fn(state)
            except GraphInterrupt:
                raise
            except Exception as e:
                _write(step, state, {"error": f"{type(e).__name__}: {e}"}, usage, t0)
                raise
            finally:
                _usage.reset(token)
            _write(step, state, jsonable(out or {}), usage, t0)
            return out
        return node
    return wrap


def _write(step: str, state: dict[str, Any], output: Any, usage: Usage, t0: float) -> None:
    write_row({
        "case_id": state["case_id"],
        "step": step,
        "model": usage.model,
        "prompt_version": usage.prompt_version,
        # the input is the state the node saw; record which keys, not a copy of everything
        "input": json.dumps({"keys": sorted(state)}),
        "output": json.dumps(output),
        "tokens_in": usage.tokens_in or None,
        "tokens_out": usage.tokens_out or None,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
    })
