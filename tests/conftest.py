"""Offline stand-ins for Postgres and OpenAI, so the whole graph runs in tests.

- the read-only tools read the generated CSVs;
- retrieval ranks the parsed guidance corpus by word overlap, with the same filter rule as SQL;
- the model is a FakeLLM whose answers each test scripts;
- audit rows and case writes are collected in lists.
"""

from __future__ import annotations

import os

# refuse any checkpointed type that app.graph.build.checkpoint_serde does not register
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

import re  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import UTC, datetime, time, timedelta  # noqa: E402
from typing import Any  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app import audit, cases, llm  # noqa: E402
from app.rag import retrieve  # noqa: E402
from app.rag.ingest import load_corpus  # noqa: E402
from app.schemas import Alert, CaseAssessment, CustomerProfile, GuidanceChunk, Txn  # noqa: E402
from app.tools import alerts, profile, transactions  # noqa: E402
from data.local_data import LocalData  # noqa: E402

DATA = LocalData()
CORPUS = [c for _, chunks in load_corpus() for c in chunks]


def csv_alert(alert_id: str) -> Alert:
    return Alert.model_validate(DATA.alerts.loc[alert_id].to_dict())


def csv_profile(customer_id: str) -> CustomerProfile:
    row = DATA.customers.loc[customer_id].to_dict()
    return CustomerProfile.model_validate({**row, "kyc_notes": row["kyc_notes"] or ""})


def csv_txns(customer_id: str, start, end, baseline_days: int = 90) -> list[Txn]:
    df = DATA.txns_by_customer[customer_id]
    ts = pd.to_datetime(df["ts"], utc=True)
    lo = datetime.combine(start - timedelta(days=baseline_days), time.min, UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, UTC)
    rows = df[(ts >= lo) & (ts < hi)].sort_values(["ts", "txn_id"])
    rows = rows.astype(object).where(rows.notna(), None)
    return [Txn.model_validate(r) for r in rows.to_dict("records")]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def lexical_retrieve(typologies, query, k=4, use_filter=True, embed=None):
    pool = [c for c in CORPUS
            if not use_filter or c.typology in typologies or c.typology == "general"]
    q = _words(query)
    scored = sorted(pool, key=lambda c: (-len(q & _words(c.section + " " + c.content)),
                                         c.chunk_id))
    return [GuidanceChunk(**c.__dict__, similarity=None) for c in scored[:k]]


def assessment(**kw: Any) -> CaseAssessment:
    base = dict(activity_summary="Activity reviewed.", benign_explanations=[], concerns=[],
                cited_chunk_ids=[], missing_information=[], confidence=0.8)
    return CaseAssessment(**(base | kw))


NARRATIVE = ("Customer\nA customer.\n\nTrigger\nA rule fired.\n\nChecks performed\nThe window."
             "\n\nFindings\nSee the pack.\n\nConclusion and reason\nAs decided.")


@dataclass
class FakeLLM:
    """Scripted answers, consumed in order; the last one repeats."""

    assessments: list[CaseAssessment | None] = field(default_factory=lambda: [assessment()])
    narratives: list[str] = field(default_factory=lambda: [NARRATIVE])
    calls: list[dict[str, Any]] = field(default_factory=list)

    def parse(self, model, messages, schema):
        self.calls.append({"kind": "parse", "messages": list(messages)})
        a = self.assessments.pop(0) if len(self.assessments) > 1 else self.assessments[0]
        return a, a.model_dump_json() if a else "", llm.Usage(1000, 200)

    def complete(self, model, messages):
        self.calls.append({"kind": "complete", "messages": list(messages)})
        n = self.narratives.pop(0) if len(self.narratives) > 1 else self.narratives[0]
        return n, llm.Usage(1500, 400)


@dataclass
class Offline:
    llm: FakeLLM
    audit_rows: list[dict[str, Any]]
    case_writes: list[tuple[str, Any]]


@pytest.fixture
def offline(monkeypatch) -> Offline:
    fake = FakeLLM()
    rows: list[dict[str, Any]] = []
    writes: list[tuple[str, Any]] = []
    monkeypatch.setattr(audit, "write_row", rows.append)
    monkeypatch.setattr(alerts, "get_alert", csv_alert)
    monkeypatch.setattr(profile, "get_profile", csv_profile)
    monkeypatch.setattr(transactions, "get_transactions", csv_txns)
    monkeypatch.setattr(retrieve, "retrieve_guidance", lexical_retrieve)
    monkeypatch.setattr(llm, "parse", fake.parse)
    monkeypatch.setattr(llm, "complete", fake.complete)
    monkeypatch.setattr(cases, "set_recommended_route",
                        lambda c, r: writes.append(("recommended", r)))
    monkeypatch.setattr(cases, "save_decision", lambda c, **kw: writes.append(("decision", kw)))
    return Offline(fake, rows, writes)
