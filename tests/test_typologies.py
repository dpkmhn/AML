"""Unit tests for compute_features and the six typology rules."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.rules.features import compute_features, review_window
from app.rules.monitoring import load_thresholds
from app.rules.typologies import detect_typologies, ramp

T = load_thresholds()
WIN_START, WIN_END = date(2026, 7, 1), date(2026, 7, 30)
INCOME = 20000.0
_seq = iter(range(1, 1_000_000))


def txn(day: date, amount: float, direction: str = "in", channel: str = "transfer",
        cp: str | None = "CP-1", country: str | None = "AE", hour: int = 10,
        reference: str | None = None) -> dict:
    return {"txn_id": f"TXN-{next(_seq):06d}", "customer_id": "CUS-0001",
            "ts": datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            "amount_aed": amount, "direction": direction, "channel": channel,
            "counterparty_id": None if channel == "cash" else cp,
            "counterparty_name": None,
            "counterparty_country": None if channel == "cash" else country,
            "reference": reference}


def background(income: float = INCOME, months=range(1, 10)) -> list[dict]:
    """Salary in and rent out every month; nothing any rule should score."""
    rows = []
    for m in months:
        rows.append(txn(date(2026, m, 27), income, cp="CP-EMP"))
        rows.append(txn(date(2026, m, 2), income * 0.3, "out", cp="CP-LANDLORD"))
    return rows


def findings(rows: list[dict], income: float = INCOME, kyc: str = "") -> dict:
    profile = {"customer_id": "CUS-0001", "declared_monthly_income_aed": income,
               "kyc_notes": kyc}
    f = compute_features(profile, pd.DataFrame(rows), WIN_START, WIN_END, T)
    return {x.typology: x for x in detect_typologies(f, T)}


def score(rows: list[dict], typology: str, income: float = INCOME) -> float:
    return findings(rows, income)[typology].score


# ---- scenario builders: n controls how strong the pattern is ---------------------------
def structuring(n: int, reference: str | None = None) -> list[dict]:
    return [txn(date(2026, 7, 5) + timedelta(days=2 * i), 47000, channel="cash",
                reference=reference) for i in range(n)]


def pass_through(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        d = date(2026, 7, 3) + timedelta(days=6 * i)
        rows.append(txn(d, 40000, cp=f"CP-IN{i}", hour=9))
        rows.append(txn(d, 37000, "out", cp=f"CP-OUT{i}", hour=20))
    return rows


def funnel(senders: int, receivers: int = 1) -> list[dict]:
    rows = [txn(date(2026, 7, 2) + timedelta(days=i % 15), 3000, cp=f"CP-S{i}")
            for i in range(senders)]
    rows += [txn(date(2026, 7, 20), 2500 * senders / receivers, "out", cp=f"CP-R{j}")
             for j in range(receivers)]
    return rows


def profile_mismatch(multiple: float) -> list[dict]:
    return [txn(date(2026, 7, 10), INCOME * multiple, cp="CP-NEW")]


def dormant(ratio: float, gap_days: int = 200) -> list[dict]:
    """Small monthly inflows, a silence of gap_days, then one inflow of ratio x the average."""
    last = date(2026, 7, 5) - timedelta(days=gap_days)
    rows = [txn(last - timedelta(days=30 * k), 1000, cp="CP-FAM") for k in range(5)]
    rows.append(txn(date(2026, 7, 5), 1000 * ratio, cp="CP-NEW"))
    return rows


def geo(n: int) -> list[dict]:
    return [txn(date(2026, 7, 4) + timedelta(days=5 * i), 15000, "out", cp=f"CP-G{i}",
                country="XB") for i in range(n)]


# ---- 1. each typology: zero, middle band, full score -----------------------------------
CASES = {
    # typology: (builder, [zero, middle, full], uses background)
    "structuring": (structuring, [2, 4, 5], True),
    "pass_through": (pass_through, [1, 3, 4], True),
    "funnel": (funnel, [6, 10, 15], False),
    "profile_mismatch": (profile_mismatch, [1.0, 2.0, 6.0], True),  # plus 1x salary
    "dormant_reactivation": (dormant, [3.0, 6.0, 15.0], False),  # prior avg 1,250/month
    "high_risk_geo": (geo, [0, 2, 3], True),
}


@pytest.mark.parametrize("typology", CASES)
def test_score_bands(typology):
    build, (zero, middle, full), with_bg = CASES[typology]
    bg = background() if with_bg else []
    assert score(bg + build(zero), typology) == 0
    assert 0.4 <= score(bg + build(middle), typology) < 0.7 + 1e-9
    assert score(bg + build(full), typology) == 1.0


def test_quiet_customer_scores_zero_everywhere():
    assert all(f.score == 0 for f in findings(background()).values())


# ---- 2. rules see shape, not intent ---------------------------------------------------
@pytest.mark.parametrize("typology", CASES)
def test_lookalike_shape_scores_the_same(typology):
    """Benign references and a KYC explanation do not lower the score: rules see shape."""
    build, (_, _, full), with_bg = CASES[typology]
    rows = (background() if with_bg else []) + build(full)
    benign = [dict(r, reference="Property sale proceeds") for r in rows]
    kyc = "Sold apartment in JVC, sale agreement and DLD transfer on file."
    assert (findings(benign, kyc=kyc)[typology].score
            == findings(rows)[typology].score == 1.0)


# ---- features: windows, evidence and edge cases ---------------------------------------
def test_ramp_boundaries():
    assert ramp(2.99, 3, 5) == 0
    assert ramp(3, 3, 5) == 0.4
    assert ramp(4, 3, 5) == 0.7
    assert ramp(5, 3, 5) == 1.0
    assert ramp(9, 3, 5) == 1.0


def test_review_window_extends_past_alert():
    start, end = review_window(WIN_START, WIN_END, T)
    assert start == WIN_START
    assert end == WIN_END + timedelta(days=T["features"]["review_lag_days"])


def test_activity_after_alert_window_is_seen():
    # Two deposits inside the alert window, three more after it: the review sees all five.
    rows = background(60000) + [txn(WIN_END - timedelta(days=2 - 2 * i), 47000, channel="cash")
                                for i in range(5)]
    assert score(rows, "structuring", 60000) == 1.0


def test_activity_before_alert_window_is_not_scored():
    rows = background(60000) + [txn(date(2026, 6, 1) + timedelta(days=2 * i), 47000,
                                    channel="cash") for i in range(5)]
    assert score(rows, "structuring", 60000) == 0


def test_structuring_needs_cash_in_band():
    near = [txn(date(2026, 7, 5) + timedelta(days=i), 47000, channel="transfer", cp=f"CP-{i}")
            for i in range(5)]
    low = [txn(date(2026, 7, 5) + timedelta(days=i), 40000, channel="cash") for i in range(5)]
    assert score(background(60000) + near, "structuring", 60000) == 0
    assert score(background(60000) + low, "structuring", 60000) == 0


def test_structuring_evidence_is_the_deposits():
    rows = background() + structuring(4)
    deposit_ids = {r["txn_id"] for r in rows if r["channel"] == "cash"}
    assert set(findings(rows)["structuring"].evidence_txn_ids) == deposit_ids


def test_pass_through_slow_outflow_is_not_an_event():
    rows = background()
    for i in range(4):
        d = date(2026, 7, 3) + timedelta(days=6 * i)
        rows.append(txn(d, 40000, cp=f"CP-IN{i}", hour=9))
        rows.append(txn(d + timedelta(days=3), 37000, "out", cp=f"CP-OUT{i}"))
    assert score(rows, "pass_through") == 0


def test_pass_through_outflow_counts_once():
    # Two inflows, one outflow big enough for either: only one event.
    d = date(2026, 7, 6)
    rows = background() + [txn(d, 40000, cp="CP-A", hour=8), txn(d, 40000, cp="CP-B", hour=9),
                           txn(d, 39000, "out", cp="CP-C", hour=12)]
    assert findings(rows)["pass_through"].evidence_txn_ids.__len__() == 2


def test_pass_through_card_spend_is_not_an_outflow():
    d = date(2026, 7, 6)
    rows = background()
    for i in range(4):
        rows.append(txn(d + timedelta(days=5 * i), 30000, cp=f"CP-IN{i}", hour=8))
        rows.append(txn(d + timedelta(days=5 * i), 29000, "out", "card", cp="CP-SHOP", hour=12))
    assert score(rows, "pass_through") == 0


def test_funnel_needs_few_receivers():
    assert score(funnel(15, receivers=2), "funnel") == 1.0
    assert score(funnel(15, receivers=3), "funnel") == 0
    assert score(funnel(15, receivers=0), "funnel") == 0


def test_profile_mismatch_evidence_is_new_money():
    rows = background() + profile_mismatch(4.0)
    ev = findings(rows)["profile_mismatch"].evidence_txn_ids
    by_id = {r["txn_id"]: r for r in rows}
    assert ev and all(by_id[i]["counterparty_id"] == "CP-NEW" for i in ev)


def test_dormant_needs_long_silence():
    assert score(dormant(15.0, gap_days=200), "dormant_reactivation") == 1.0
    assert score(dormant(15.0, gap_days=120), "dormant_reactivation") == 0


def test_dormant_needs_history():
    """With no transaction before the window there is no silence to measure."""
    rows = [txn(date(2026, 7, 5), 50000, cp="CP-NEW")]
    assert score(rows, "dormant_reactivation") == 0


def test_high_risk_geo_lists_countries():
    rows = background() + geo(2) + [txn(date(2026, 7, 20), 5000, cp="CP-Q", country="XA")]
    f = findings(rows)["high_risk_geo"]
    assert f.score == 1.0
    assert "XA, XB" in f.rule_explanation


@pytest.mark.parametrize("typology", CASES)
def test_every_scoring_finding_has_evidence(typology):
    build, (_, middle, _), with_bg = CASES[typology]
    f = findings((background() if with_bg else []) + build(middle))[typology]
    assert f.score >= 0.4 and f.evidence_txn_ids
