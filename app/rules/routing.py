"""decide_route: deterministic routing from typology scores, the assessment and the profile.

The LLM never picks the route. It contributes facts (benign explanations, missing information,
confidence), and code checks those facts before they count:

- an explanation counts only with a KYC quote found word for word in kyc_notes, or with
  transaction IDs that exist in this case;
- escalation rules run first, so nothing below them can hide an escalation;
- when no rule matches cleanly, the answer is Needs more info, never Close.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

from app.rules.monitoring import load_thresholds
from app.schemas import BenignExplanation, CaseAssessment, RouteDecision, TypologyFinding

MIN_QUOTE_CHARS = 12  # shorter quotes ("on file") prove nothing


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_notes(quote: str | None, kyc_notes: str) -> bool:
    """True when the quote appears in kyc_notes, ignoring case and whitespace."""
    if not quote:
        return False
    q = _norm(quote).strip("\"'")
    return len(q) >= MIN_QUOTE_CHARS and q in _norm(kyc_notes)


def is_supported(b: BenignExplanation, kyc_notes: str, known_txn_ids: Collection[str]) -> bool:
    """An explanation is supported by a verified KYC quote or by known transaction IDs."""
    if quote_in_notes(b.kyc_quote, kyc_notes):
        return True
    return bool(b.evidence_txn_ids) and all(i in known_txn_ids for i in b.evidence_txn_ids)


def decide_route(findings: list[TypologyFinding], assessment: CaseAssessment, *,
                 risk_rating: str, kyc_notes: str, known_txn_ids: Collection[str],
                 t: Mapping[str, Any] | None = None) -> RouteDecision:
    p = (t or load_thresholds())["routing"]
    fired = [f for f in findings if f.score >= p["high_risk_escalate_score"]]
    explained = {b.typology for b in assessment.benign_explanations
                 if is_supported(b, kyc_notes, known_txn_ids)}

    def decision(route: str, rule_id: str, reasons: list[str]) -> RouteDecision:
        return RouteDecision(
            route=route, rule_ids=[rule_id], reasons=reasons,
            fired_typologies=[f.typology for f in fired],
            explained_typologies=sorted(explained & {f.typology for f in fired}))

    # R1: a strong typology with no supported benign explanation
    strong = [f for f in findings if f.score >= p["escalate_score"] and f.typology not in explained]
    if strong:
        return decision("escalate", "R1", [
            f"{f.typology} scored {f.score:.2f} (>= {p['escalate_score']}) with no benign "
            f"explanation supported by evidence" for f in strong])

    # R2: a high-risk customer with any typology at or above the lower cut-off
    if risk_rating == "high" and fired:
        return decision("escalate", "R2", [
            f"High-risk customer and {f.typology} scored {f.score:.2f} "
            f"(>= {p['high_risk_escalate_score']})" for f in fired])

    # R3: information missing that would change the decision
    gaps = [m.item for m in assessment.missing_information if m.changes_decision]
    if gaps:
        return decision("needs_info", "R3", [f"Missing: {g}" for g in gaps])

    # R5: low confidence never closes
    if assessment.confidence < p["min_close_confidence"]:
        return decision("needs_info", "R5", [
            f"Assessment confidence {assessment.confidence:.2f} is below "
            f"{p['min_close_confidence']}"])

    # R4: close only when every fired typology is explained with evidence
    unexplained = [f.typology for f in fired if f.typology not in explained]
    if not unexplained:
        reasons = ([f"{ty} explained with evidence" for ty in sorted(explained & {
            f.typology for f in fired})] or ["No typology scored at or above "
                                             f"{p['high_risk_escalate_score']}"])
        return decision("close", "R4", reasons)

    # R0: safety net
    return decision("needs_info", "R0", [
        f"{ty} scored between {p['high_risk_escalate_score']} and {p['escalate_score']} "
        f"without a supported explanation; not safe to close" for ty in unexplained])
