"""Unit tests for decide_route: one or more per routing rule, plus the boundaries."""

import pytest

from app.rules.monitoring import load_thresholds
from app.rules.routing import decide_route, quote_in_notes
from app.schemas import BenignExplanation, CaseAssessment, MissingInfo, TypologyFinding

T = load_thresholds()
KYC = ("Sold apartment in JVC for AED 1,200,000, Aug 2026; sale agreement and DLD transfer "
       "on file. Last CDD review Mar 2024.")
KNOWN = {"TXN-000101", "TXN-000102"}


def finding(typology: str = "profile_mismatch", score: float = 0.8) -> TypologyFinding:
    return TypologyFinding(typology=typology, score=score, evidence_txn_ids=["TXN-000101"],
                           rule_explanation="test")


def explained(typology: str = "profile_mismatch", quote: str | None = "Sold apartment in JVC",
              txn_ids: list[str] | None = None) -> BenignExplanation:
    return BenignExplanation(typology=typology, explanation="documented sale",
                             kyc_quote=quote, evidence_txn_ids=txn_ids or [])


def assessment(explanations=(), missing=(), confidence: float = 0.9) -> CaseAssessment:
    return CaseAssessment(activity_summary="test", benign_explanations=list(explanations),
                          concerns=[], cited_chunk_ids=[], missing_information=list(missing),
                          confidence=confidence)


def route(findings, a, risk: str = "low", kyc: str = KYC, known=KNOWN):
    return decide_route(findings, a, risk_rating=risk, kyc_notes=kyc, known_txn_ids=known, t=T)


# ---- R1 -------------------------------------------------------------------------------
def test_r1_strong_unexplained_escalates():
    d = route([finding(score=0.8)], assessment())
    assert (d.route, d.rule_ids) == ("escalate", ["R1"])


def test_r1_strong_but_explained_does_not_escalate():
    d = route([finding(score=0.8)], assessment([explained()]))
    assert (d.route, d.rule_ids) == ("close", ["R4"])


def test_r1_explanation_must_match_the_typology():
    d = route([finding("structuring", 0.9)], assessment([explained("profile_mismatch")]))
    assert d.route == "escalate"


def test_r1_one_explained_one_not_still_escalates():
    d = route([finding("profile_mismatch", 1.0), finding("structuring", 0.9)],
              assessment([explained("profile_mismatch")]))
    assert (d.route, d.rule_ids) == ("escalate", ["R1"])
    assert d.explained_typologies == ["profile_mismatch"]


# ---- R2 -------------------------------------------------------------------------------
def test_r2_high_risk_with_typology_escalates_even_when_explained():
    d = route([finding(score=0.45)], assessment([explained()]), risk="high")
    assert (d.route, d.rule_ids) == ("escalate", ["R2"])


def test_r2_high_risk_without_typology_can_close():
    d = route([finding(score=0.3)], assessment(), risk="high")
    assert d.route == "close"


# ---- R3 -------------------------------------------------------------------------------
def test_r3_beats_r4_decision_relevant_gap():
    gap = MissingInfo(item="source of funds documents", changes_decision=True)
    d = route([finding(score=0.8)], assessment([explained()], [gap]))
    assert (d.route, d.rule_ids) == ("needs_info", ["R3"])


def test_r3_irrelevant_gap_does_not_block_close():
    gap = MissingInfo(item="customer's middle name", changes_decision=False)
    d = route([finding(score=0.8)], assessment([explained()], [gap]))
    assert d.route == "close"


def test_r1_beats_r3():
    gap = MissingInfo(item="source of funds documents", changes_decision=True)
    d = route([finding(score=0.9)], assessment([], [gap]))
    assert d.route == "escalate"


# ---- R5 -------------------------------------------------------------------------------
def test_r5_low_confidence_never_closes():
    d = route([finding(score=0.8)], assessment([explained()], confidence=0.55))
    assert (d.route, d.rule_ids) == ("needs_info", ["R5"])


# ---- R4 and R0 ------------------------------------------------------------------------
def test_r4_nothing_fired_closes():
    d = route([finding(score=0.0)], assessment())
    assert (d.route, d.rule_ids) == ("close", ["R4"])


def test_r0_middle_score_unexplained_is_not_closed():
    d = route([finding(score=0.5)], assessment())
    assert (d.route, d.rule_ids) == ("needs_info", ["R0"])


# ---- explanations must be supported ---------------------------------------------------
def test_fabricated_quote_does_not_count():
    d = route([finding(score=0.8)], assessment([explained(quote="Inherited villa in Jumeirah")]))
    assert d.route == "escalate"


def test_quote_too_short_does_not_count():
    d = route([finding(score=0.8)], assessment([explained(quote="on file")]))
    assert d.route == "escalate"


def test_quote_match_ignores_case_and_whitespace():
    assert quote_in_notes("sold  apartment in\njvc", KYC)
    assert not quote_in_notes("sold apartment in Marina", KYC)
    assert not quote_in_notes(None, KYC)


def test_known_transaction_ids_support_an_explanation():
    d = route([finding(score=0.8)], assessment([explained(quote=None, txn_ids=["TXN-000102"])]))
    assert d.route == "close"


def test_unknown_transaction_ids_do_not_count():
    d = route([finding(score=0.8)],
              assessment([explained(quote=None, txn_ids=["TXN-000102", "TXN-999999"])]))
    assert d.route == "escalate"


def test_explanation_without_quote_or_ids_does_not_count():
    d = route([finding(score=0.8)], assessment([explained(quote=None)]))
    assert d.route == "escalate"


# ---- boundaries at exactly 0.4 and 0.7 -------------------------------------------------
@pytest.mark.parametrize("score, expected", [(0.69, "needs_info"), (0.7, "escalate")])
def test_escalate_boundary(score, expected):
    assert route([finding(score=score)], assessment()).route == expected


@pytest.mark.parametrize("score, expected", [(0.39, "close"), (0.4, "escalate")])
def test_high_risk_boundary(score, expected):
    assert route([finding(score=score)], assessment(), risk="high").route == expected


@pytest.mark.parametrize("confidence, expected", [(0.59, "needs_info"), (0.6, "close")])
def test_confidence_boundary(confidence, expected):
    d = route([finding(score=0.8)], assessment([explained()], confidence=confidence))
    assert d.route == expected


@pytest.mark.parametrize("score, expected", [(0.39, "close"), (0.4, "needs_info")])
def test_fired_boundary(score, expected):
    assert route([finding(score=score)], assessment()).route == expected
