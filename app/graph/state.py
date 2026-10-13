"""CaseState: everything one case accumulates as it moves through the graph.

Values are Pydantic models inside a TypedDict; the checkpointer serialises them. Each node
returns only the keys it sets.
"""

from __future__ import annotations

from typing import TypedDict

from app.schemas import (
    Alert,
    AnalystDecision,
    CaseAssessment,
    CustomerProfile,
    Features,
    GuidanceChunk,
    RouteDecision,
    RunConfig,
    Txn,
    TypologyFinding,
)


class CaseState(TypedDict, total=False):
    case_id: str
    alert_id: str
    alert: Alert
    profile: CustomerProfile
    txns: list[Txn]  # history_days before the review window to its end
    features: Features
    findings: list[TypologyFinding]
    guidance: list[GuidanceChunk]
    flagged_txn_ids: list[str]  # references that read like instructions (app/guard.py)
    assessment: CaseAssessment
    assessment_errors: list[str]  # post-check failures left after the retry
    route: RouteDecision
    review: AnalystDecision
    narrative: str
    narrative_errors: list[str]
    run_config: RunConfig  # model, prompt version, experiment flags


def review_txns(state: CaseState) -> list[Txn]:
    """The transactions an analyst reviews: the baseline and the review window.

    state["txns"] reaches further back, for dormancy; the model and the pack see only these.
    """
    f = state["features"]
    return [t for t in state["txns"] if f.baseline_start <= t.ts.date() <= f.review_end]
