"""decide_route: deterministic routing from typology scores, the assessment and the profile.

The LLM never picks the route. It contributes facts (benign explanations, missing information,
confidence), and code checks those facts before they count:

- an explanation counts only with a KYC quote found word for word in kyc_notes, or with
  transaction IDs that exist in this case;
- and only for what it covers: the supported explanations of a typology must name
  transactions making up `min_explained_share` of the finding's evidence amount, so a true
  quote about the salary cannot explain the credits that fired the rule;
- escalation rules run first (R1, R2, R6, R7), so nothing below them can hide an escalation;
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


def explained_share(f: TypologyFinding, explanations: list[BenignExplanation],
                    txn_amounts: Mapping[str, float]) -> float:
    """Share of the finding's evidence amount named by these explanations' transaction IDs.
    A finding with no evidence amount is fully covered by any explanation."""
    named = {i for b in explanations for i in b.evidence_txn_ids}
    total = sum(txn_amounts.get(i, 0.0) for i in f.evidence_txn_ids)
    if total <= 0:
        return 1.0 if explanations else 0.0
    return sum(txn_amounts.get(i, 0.0) for i in f.evidence_txn_ids if i in named) / total


def decide_route(findings: list[TypologyFinding], assessment: CaseAssessment, *,
                 risk_rating: str, kyc_notes: str, txn_amounts: Mapping[str, float],
                 flagged_txn_ids: Collection[str] = (),
                 t: Mapping[str, Any] | None = None) -> RouteDecision:
    """txn_amounts maps every transaction ID in the case's review window to its amount;
    flagged_txn_ids are the references app/guard.py found instruction-like."""
    p = (t or load_thresholds())["routing"]
    fired = [f for f in findings if f.score >= p["high_risk_escalate_score"]]
    supported = [b for b in assessment.benign_explanations
                 if is_supported(b, kyc_notes, txn_amounts)]
    explained = {f.typology for f in findings
                 if explained_share(f, [b for b in supported if b.typology == f.typology],
                                    txn_amounts) >= p["min_explained_share"]}

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

    # R6 (escalation criterion 3): a customer-written field tries to instruct the reviewer,
    # alongside any typology signal, explained or not
    if flagged_txn_ids and fired:
        return decision("escalate", "R6", [
            f"Instruction-like payment reference in {', '.join(sorted(flagged_txn_ids))} "
            f"alongside {', '.join(f.typology for f in fired)}"])

    # R7 (escalation criterion 4): several typologies together, at least one unexplained.
    # Profile mismatch does not count: a large inflow accompanies most other patterns.
    several = [f for f in fired if f.typology not in p["combination_excludes"]]
    open_ = [f.typology for f in several if f.typology not in explained]
    if len(several) >= 2 and open_:
        return decision("escalate", "R7", [
            f"{len(several)} typologies together ({', '.join(f.typology for f in several)}), "
            f"unexplained: {', '.join(open_)}"])

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
