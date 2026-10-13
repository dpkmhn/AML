"""Unit tests for decide_route: one or more per routing rule, plus the boundaries."""

import pytest

from app.rules.monitoring import load_thresholds
from app.rules.routing import decide_route, quote_in_notes
from app.schemas import BenignExplanation, CaseAssessment, MissingInfo, TypologyFinding

T = load_thresholds()
KYC = ("Sold apartment in JVC for AED 1,200,000, Aug 2026; sale agreement and DLD transfer "
       "on file. Last CDD review Mar 2024.")
# transaction ID -> amount in AED: the case's review transactions
KNOWN = {"TXN-000101": 1_200_000.0, "TXN-000102": 15_000.0, "TXN-000103": 300_000.0}


def finding(typology: str = "profile_mismatch", score: float = 0.8,
            txn_ids: tuple[str, ...] = ("TXN-000101",)) -> TypologyFinding:
    return TypologyFinding(typology=typology, score=score, evidence_txn_ids=list(txn_ids),
                           rule_explanation="test")


def explained(typology: str = "profile_mismatch", quote: str | None = "Sold apartment in JVC",
              txn_ids: tuple[str, ...] = ("TXN-000101",)) -> BenignExplanation:
    return BenignExplanation(typology=typology, explanation="documented sale",
                             kyc_quote=quote, evidence_txn_ids=list(txn_ids))


def assessment(explanations=(), missing=(), confidence: float = 0.9) -> CaseAssessment:
    return CaseAssessment(activity_summary="test", benign_explanations=list(explanations),
                          concerns=[], cited_chunk_ids=[], missing_information=list(missing),
                          confidence=confidence)


def route(findings, a, risk: str = "low", kyc: str = KYC, known=KNOWN):
    return decide_route(findings, a, risk_rating=risk, kyc_notes=kyc, txn_amounts=known, t=T)


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
# IDs that cover the finding but include an unknown one: only the quote could support these
UNSUPPORTED_IDS = ("TXN-000101", "TXN-999999")


def test_valid_quote_supports_ids_that_cover_the_finding():
    d = route([finding(score=0.8)], assessment([explained(txn_ids=UNSUPPORTED_IDS)]))
    assert d.route == "close"


def test_fabricated_quote_does_not_count():
    d = route([finding(score=0.8)], assessment([explained(quote="Inherited villa in Jumeirah",
                                                                txn_ids=UNSUPPORTED_IDS)]))
    assert d.route == "escalate"


def test_quote_too_short_does_not_count():
    d = route([finding(score=0.8)],
              assessment([explained(quote="on file", txn_ids=UNSUPPORTED_IDS)]))
    assert d.route == "escalate"


def test_quote_match_ignores_case_and_whitespace():
    assert quote_in_notes("sold  apartment in\njvc", KYC)
    assert not quote_in_notes("sold apartment in Marina", KYC)
    assert not quote_in_notes(None, KYC)


def test_known_transaction_ids_support_an_explanation():
    d = route([finding(score=0.8)], assessment([explained(quote=None)]))
    assert d.route == "close"


def test_unknown_transaction_ids_do_not_count():
    d = route([finding(score=0.8)],
              assessment([explained(quote=None, txn_ids=("TXN-000101", "TXN-999999"))]))
    assert d.route == "escalate"


def test_explanation_without_quote_or_ids_does_not_count():
    d = route([finding(score=0.8)], assessment([explained(quote=None, txn_ids=())]))
    assert d.route == "escalate"


# ---- explanations must cover the finding (stage 4.2) -----------------------------------
def test_true_quote_about_other_transactions_does_not_explain():
    """The baseline failure: a real KYC quote (the salary) offered for credits it does not
    cover. The quote is verified, but it explains none of the finding's amount."""
    d = route([finding(score=1.0)], assessment([explained(txn_ids=("TXN-000102",))]))
    assert (d.route, d.rule_ids) == ("escalate", ["R1"])
    assert d.explained_typologies == []


def test_quote_without_transaction_ids_does_not_explain():
    d = route([finding(score=0.8)], assessment([explained(txn_ids=())]))
    assert d.route == "escalate"


def test_coverage_is_by_amount_not_count():
    f = finding(score=0.8, txn_ids=("TXN-000101", "TXN-000102", "TXN-000103"))
    # two of three IDs, but only AED 315,000 of 1,515,000
    small = route([f], assessment([explained(txn_ids=("TXN-000102", "TXN-000103"))]))
    assert small.route == "escalate"
    # one of three IDs, AED 1,200,000 of 1,515,000
    large = route([f], assessment([explained(txn_ids=("TXN-000101",))]))
    assert large.route == "close"


def test_coverage_adds_up_across_explanations_of_one_typology():
    f = finding(score=0.8, txn_ids=("TXN-000101", "TXN-000103"))
    d = route([f], assessment([explained(txn_ids=("TXN-000103",)),
                               explained(quote=None, txn_ids=("TXN-000101",))]))
    assert d.route == "close"


def test_unsupported_explanation_adds_no_coverage():
    f = finding(score=0.8, txn_ids=("TXN-000101", "TXN-000103"))
    d = route([f], assessment([explained(txn_ids=("TXN-000103",)),
                               explained(quote="Inherited villa in Jumeirah",
                                         txn_ids=("TXN-000101", "TXN-999999"))]))
    assert d.route == "escalate"


@pytest.mark.parametrize("covered, expected", [(("TXN-000103",), "escalate"),
                                               (("TXN-000103", "TXN-000102"), "close")])
def test_coverage_boundary(covered, expected):
    # 300,000 of 615,000 is 48.8%; adding 15,000 makes 51.2%
    f = finding(score=0.8, txn_ids=("TXN-000102", "TXN-000103", "TXN-000104"))
    known = {**KNOWN, "TXN-000104": 300_000.0}
    assert route([f], assessment([explained(txn_ids=covered)]), known=known).route == expected


def test_finding_without_evidence_is_explained_by_any_supported_explanation():
    d = route([finding(score=0.8, txn_ids=())], assessment([explained()]))
    assert d.route == "close"


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


# ---- R6 and R7: written escalation criteria 3 and 4 (stage 4.3) -------------------------
def route_flagged(findings, a, flagged=("TXN-000102",), risk: str = "low"):
    return decide_route(findings, a, risk_rating=risk, kyc_notes=KYC, txn_amounts=KNOWN,
                        flagged_txn_ids=list(flagged), t=T)


def test_r6_instruction_reference_with_a_moderate_signal_escalates():
    # without the flag this is R0 needs_info (0.5, unexplained)
    d = route_flagged([finding(score=0.5)], assessment())
    assert (d.route, d.rule_ids) == ("escalate", ["R6"])
    assert "TXN-000102" in d.reasons[0]


def test_r6_applies_even_when_the_typology_is_explained():
    d = route_flagged([finding(score=0.8)], assessment([explained()]))
    assert (d.route, d.rule_ids) == ("escalate", ["R6"])


def test_r6_needs_a_typology_signal():
    d = route_flagged([finding(score=0.3)], assessment())
    assert d.route == "close"


def test_r1_still_comes_first():
    d = route_flagged([finding(score=0.9)], assessment())
    assert d.rule_ids == ["R1"]


def test_r7_two_typologies_besides_profile_mismatch_escalate():
    f = [finding("pass_through", 0.5), finding("high_risk_geo", 0.5, ("TXN-000103",))]
    d = route(f, assessment())
    assert (d.route, d.rule_ids) == ("escalate", ["R7"])


def test_r7_profile_mismatch_does_not_count_towards_several():
    f = [finding("profile_mismatch", 0.5), finding("structuring", 0.5, ("TXN-000103",))]
    d = route(f, assessment())
    assert (d.route, d.rule_ids) == ("needs_info", ["R0"])


def test_r7_all_explained_does_not_escalate():
    f = [finding("pass_through", 0.5), finding("high_risk_geo", 0.5)]
    d = route(f, assessment([explained("pass_through"), explained("high_risk_geo")]))
    assert d.route == "close"


def test_r7_one_explained_one_not_escalates():
    f = [finding("pass_through", 0.5), finding("high_risk_geo", 0.5, ("TXN-000103",))]
    d = route(f, assessment([explained("pass_through")]))
    assert (d.route, d.rule_ids) == ("escalate", ["R7"])
