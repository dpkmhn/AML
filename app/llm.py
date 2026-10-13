"""The only module that talks to OpenAI: embeddings, structured parses and plain text.

Every call returns its token usage so nodes can pass it to the audit log. Tests replace these
functions; nothing else imports the SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@cache
def client() -> OpenAI:
    key = settings.openai_api_key
    if key is None or not key.get_secret_value().strip():
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    return OpenAI(api_key=key.get_secret_value())


def _usage(resp: Any) -> Usage:
    u = getattr(resp, "usage", None)
    return Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


def embed(texts: list[str]) -> list[list[float]]:
    resp = client().embeddings.create(model=settings.embed_model, input=texts,
                                      dimensions=settings.embed_dim)
    return [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]


def parse[M: BaseModel](model: str, messages: list[dict[str, str]],
                        schema: type[M]) -> tuple[M | None, str, Usage]:
    """Structured output at temperature 0. Returns (parsed or None, raw text, usage); None
    means the model refused or the output did not fit the schema."""
    resp = client().chat.completions.parse(model=model, messages=messages,
                                           response_format=schema, temperature=0)
    msg = resp.choices[0].message
    return msg.parsed, msg.content or msg.refusal or "", _usage(resp)


def complete(model: str, messages: list[dict[str, str]]) -> tuple[str, Usage]:
    resp = client().chat.completions.create(model=model, messages=messages, temperature=0)
    return resp.choices[0].message.content or "", _usage(resp)
