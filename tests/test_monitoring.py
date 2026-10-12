"""Unit tests for the six monitoring rules and alert consolidation."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.rules.monitoring import load_thresholds, run_monitoring

START, END = date(2026, 4, 1), date(2026, 9, 30)
_seq = iter(range(1, 1_000_000))


def txn(day: date, amount: float, direction: str = "in", channel: str = "transfer",
        cp: str | None = "CP-1", country: str | None = "AE", hour: int = 10) -> dict:
    return {"txn_id": f"TXN-{next(_seq):06d}", "customer_id": "CUS-0001",
            "ts": datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            "amount_aed": amount, "direction": direction, "channel": channel,
            "counterparty_id": cp, "counterparty_country": country}


def background(income: float = 20000) -> list[dict]:
    """A quiet salaried customer: salary and rent each month, nothing unusual."""
    rows = []
    for m in range(4, 10):
        rows.append(txn(date(2026, m, 27), income, cp="CP-EMP"))
        rows.append(txn(date(2026, m, 2), income * 0.3, "out", cp="CP-LANDLORD"))
    return rows


def alerts_for(rows: list[dict], income: float = 20000) -> pd.DataFrame:
    customers = pd.DataFrame([{"customer_id": "CUS-0001",
                               "declared_monthly_income_aed": income}])
    return run_monitoring(customers, pd.DataFrame(rows), START, END, load_thresholds())


def rules(rows: list[dict], income: float = 20000) -> list[str]:
    return alerts_for(rows, income).rule_id.tolist()


def test_quiet_customer_raises_nothing():
    assert rules(background()) == []


def test_structuring_three_cash_deposits_in_band():
    d = date(2026, 7, 6)
    rows = background(60000) + [txn(d + timedelta(days=i * 3), 46000, channel="cash", cp=None)
                                for i in range(3)]
    assert rules(rows, 60000) == ["TM-STR-01"]


def test_structuring_ignores_deposits_below_band():
    d = date(2026, 7, 6)
    rows = background(60000) + [txn(d + timedelta(days=i * 3), 40000, channel="cash", cp=None)
                                for i in range(3)]
    assert "TM-STR-01" not in rules(rows, 60000)


def test_pass_through_two_quick_cycles():
    rows = background()
    for d in (date(2026, 7, 6), date(2026, 7, 14)):
        rows.append(txn(d, 30000, cp="CP-A", hour=9))
        rows.append(txn(d, 27000, "out", cp="CP-B", hour=20))
    assert "TM-PT-01" in rules(rows)


def test_pass_through_needs_outflow_within_horizon():
    rows = background()
    for d in (date(2026, 7, 6), date(2026, 7, 14)):
        rows.append(txn(d, 30000, cp="CP-A"))
        rows.append(txn(d + timedelta(days=5), 27000, "out", cp="CP-B"))
    assert "TM-PT-01" not in rules(rows)


def test_funnel_many_senders_few_receivers():
    d = date(2026, 7, 6)
    rows = [txn(d + timedelta(days=i), 2000, cp=f"CP-S{i}") for i in range(10)]
    rows.append(txn(d + timedelta(days=12), 18000, "out", cp="CP-R"))
    assert rules(rows, 5000) == ["TM-FUN-01"]


def test_funnel_not_raised_when_money_spreads_out():
    d = date(2026, 7, 6)
    rows = [txn(d + timedelta(days=i), 2000, cp=f"CP-S{i}") for i in range(10)]
    rows += [txn(d + timedelta(days=12), 4000, "out", cp=f"CP-R{i}") for i in range(4)]
    assert "TM-FUN-01" not in rules(rows, 50000)


def test_profile_mismatch_inflow_above_twice_income():
    rows = background() + [txn(date(2026, 7, 10), 30000, cp="CP-X")]
    assert rules(rows) == ["TM-PM-01"]


def test_dormant_reactivation():
    rows = [txn(date(2025, 10, 1) + timedelta(days=30 * k), 1000, cp="CP-F") for k in range(4)]
    rows += [txn(date(2026, 8, 20), 20000, cp="CP-N")]
    assert "TM-DOR-01" in rules(rows, 50000)


def test_dormant_needs_long_gap():
    rows = [txn(date(2026, 4, 1) + timedelta(days=30 * k), 1000, cp="CP-F") for k in range(3)]
    rows += [txn(date(2026, 8, 20), 20000, cp="CP-N")]
    assert "TM-DOR-01" not in rules(rows, 50000)


def test_high_risk_geo_single_transfer():
    rows = background() + [txn(date(2026, 7, 10), 3000, "out", cp="CP-Z", country="XB")]
    assert rules(rows) == ["TM-GEO-01"]


def test_consolidation_keeps_most_specific_rule():
    # Structuring deposits also push inflow far above income: one alert, under TM-STR-01.
    d = date(2026, 7, 6)
    rows = background(20000) + [txn(d + timedelta(days=i * 2), 47000, channel="cash", cp=None)
                                for i in range(4)]
    assert rules(rows, 20000) == ["TM-STR-01"]


@pytest.mark.parametrize("gap_days, expected", [(10, 1), (70, 2)])
def test_rule_suppression(gap_days, expected):
    first = date(2026, 6, 1)
    rows = background() + [txn(first, 3000, "out", cp="CP-Z", country="XA"),
                           txn(first + timedelta(days=gap_days), 3000, "out", cp="CP-Z",
                               country="XA")]
    assert rules(rows).count("TM-GEO-01") == expected
