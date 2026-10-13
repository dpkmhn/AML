"""Pydantic models shared by the rules, the graph, the API and the evaluation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator

TypologyName = Literal["structuring", "pass_through", "funnel", "profile_mismatch",
                       "dormant_reactivation", "high_risk_geo"]
TYPOLOGIES: tuple[TypologyName, ...] = ("structuring", "pass_through", "funnel",
                                        "profile_mismatch", "dormant_reactivation",
                                        "high_risk_geo")

Route = Literal["close", "escalate", "needs_info"]
RiskRating = Literal["low", "medium", "high"]


class Alert(BaseModel):
    alert_id: str
    customer_id: str
    rule_id: str
    window_start: date
    window_end: date
    created_at: datetime
    status: Literal["open", "in_review", "closed"]


class CustomerProfile(BaseModel):
    customer_id: str
    full_name: str
    segment: Literal["salaried", "business", "student", "retiree"]
    occupation: str
    declared_monthly_income_aed: float
    expected_activity: str
    risk_rating: RiskRating
    is_pep: bool
    nationality: str
    account_opened: date
    kyc_notes: str


class Txn(BaseModel):
    txn_id: str
    customer_id: str
    ts: datetime
    amount_aed: float
    direction: Literal["in", "out"]
    channel: Literal["cash", "transfer", "card"]
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    counterparty_country: str | None = None
    reference: str | None = None  # customer-written: untrusted


class GuidanceChunk(BaseModel):
    chunk_id: str
    doc_id: str
    typology: str
    section: str
    content: str
    similarity: float | None = None


class RunConfig(BaseModel):
    """What a run used, so every audit row and evaluation result can be traced to it."""

    model: str
    prompt_version: int
    use_filter: bool = True  # metadata filter in retrieval (stage 4.3 turns it off)
    use_guard: bool = True  # quoted data block for payment references (stage 4.3 turns it off)


class Features(BaseModel):
    """Numbers the typology rules score, each with the transaction IDs behind it.

    The review window runs from the alert's window start to the review date (window end plus
    the review lag), so activity that continued after the alert fired is visible. The baseline
    is the `baseline_days` before the review window.
    """

    customer_id: str
    review_start: date
    review_end: date
    baseline_start: date

    # Summary of the review window, for the LLM and the analyst pack
    txn_count: int
    inflow_aed: float
    outflow_aed: float
    in_out_ratio: float | None
    cash_share: float
    max_single_txn_aed: float
    baseline_monthly_inflow_aed: float

    # Structuring: cash deposits in the band just below the reporting threshold (best 14 days)
    cash_near_threshold_count: int
    cash_near_threshold_txn_ids: list[str]

    # Pass-through: large inflows mostly sent on within the horizon (best 30 days)
    pass_through_events: int
    pass_through_txn_ids: list[str]

    # Funnel: many distinct senders, few receivers (best 30 days)
    distinct_senders: int
    distinct_receivers: int
    funnel_txn_ids: list[str]

    # Profile mismatch: inflow against declared income (best 30 days)
    max_inflow_30d_aed: float
    inflow_to_income_ratio: float
    profile_mismatch_txn_ids: list[str]

    # Dormant reactivation: longest silence before activity in the review window
    days_inactive_before_activity: int
    inflow_vs_prior_ratio: float
    dormant_txn_ids: list[str]

    # High-risk geography
    high_risk_txn_count: int
    high_risk_countries: list[str]
    high_risk_txn_ids: list[str]


class TypologyFinding(BaseModel):
    typology: TypologyName
    score: float = Field(ge=0, le=1)
    evidence_txn_ids: list[str]
    rule_explanation: str


class BenignExplanation(BaseModel):
    typology: TypologyName
    explanation: str
    kyc_quote: str | None = None  # exact words from kyc_notes
    evidence_txn_ids: list[str] = []
    cited_chunk_ids: list[str] = []  # the guidance section it satisfies


class MissingInfo(BaseModel):
    item: str
    changes_decision: bool


class CaseAssessment(BaseModel):
    activity_summary: str
    benign_explanations: list[BenignExplanation]
    concerns: list[str]
    cited_chunk_ids: list[str]
    missing_information: list[MissingInfo]
    confidence: float = Field(ge=0, le=1)


class RouteDecision(BaseModel):
    route: Route
    rule_ids: list[str]  # routing rules that decided it: R1..R5, R0 default
    reasons: list[str]
    fired_typologies: list[TypologyName]
    explained_typologies: list[TypologyName]


class AnalystDecision(BaseModel):
    """The human's call. Validate with context={"recommended": <route>}: overriding the
    recommendation needs a reason."""

    reviewer: str = Field(min_length=1)
    final_route: Route
    override_reason: str | None = None
    edits: str | None = None  # the analyst's corrections to the pack, if any

    @model_validator(mode="after")
    def reason_required_on_override(self, info: ValidationInfo) -> AnalystDecision:
        recommended = (info.context or {}).get("recommended")
        reason = (self.override_reason or "").strip()
        if recommended and self.final_route != recommended and not reason:
            raise ValueError(f"override_reason is required when overriding the recommended "
                             f"route ({recommended} -> {self.final_route})")
        return self
