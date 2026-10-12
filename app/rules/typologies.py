"""Six typology rules: pure functions (Features, thresholds) -> TypologyFinding.

Scores ramp linearly from 0.4 at the soft threshold to 1.0 at the hard one, and are 0 below
the soft threshold, so the routing cut-offs (0.4 and 0.7) mean something. Rules see the shape
of the activity, not its intent: a benign look-alike scores as high as the real thing. Telling
them apart is the job of the profile, the evidence and the analyst.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.rules.monitoring import load_thresholds
from app.schemas import Features, TypologyFinding


def ramp(x: float, soft: float, hard: float) -> float:
    if x < soft:
        return 0.0
    if hard <= soft or x >= hard:
        return 1.0
    return round(0.4 + 0.6 * (x - soft) / (hard - soft), 3)


def structuring(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p, thr = t["structuring"], t["cash_reporting_threshold_aed"]
    n = f.cash_near_threshold_count
    return TypologyFinding(
        typology="structuring",
        score=ramp(n, p["soft_count"], p["hard_count"]),
        evidence_txn_ids=f.cash_near_threshold_txn_ids,
        rule_explanation=(f"{n} cash deposits between AED {p['band_low'] * thr:,.0f} and "
                          f"AED {thr:,.0f} within {p['window_days']} days "
                          f"(soft {p['soft_count']}, hard {p['hard_count']})"),
    )


def pass_through(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p = t["pass_through"]
    n = f.pass_through_events
    return TypologyFinding(
        typology="pass_through",
        score=ramp(n, p["soft_events"], p["hard_events"]),
        evidence_txn_ids=f.pass_through_txn_ids,
        rule_explanation=(f"{n} inflows of AED {p['min_inflow_aed']:,.0f} or more with "
                          f"{p['outflow_share']:.0%} or more sent out within {p['max_hours']} h, "
                          f"within {p['window_days']} days "
                          f"(soft {p['soft_events']}, hard {p['hard_events']})"),
    )


def funnel(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p = t["funnel"]
    few_receivers = 1 <= f.distinct_receivers <= p["max_receivers"]
    score = ramp(f.distinct_senders, p["soft_senders"], p["hard_senders"]) if few_receivers else 0
    return TypologyFinding(
        typology="funnel",
        score=score,
        evidence_txn_ids=f.funnel_txn_ids,
        rule_explanation=(f"{f.distinct_senders} distinct senders and {f.distinct_receivers} "
                          f"receivers by transfer within {p['window_days']} days "
                          f"(senders soft {p['soft_senders']}, hard {p['hard_senders']}; "
                          f"receivers at most {p['max_receivers']})"),
    )


def profile_mismatch(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p = t["profile_mismatch"]
    x = f.inflow_to_income_ratio
    return TypologyFinding(
        typology="profile_mismatch",
        score=ramp(x, p["soft_ratio"], p["hard_ratio"]),
        evidence_txn_ids=f.profile_mismatch_txn_ids,
        rule_explanation=(f"Inflow of AED {f.max_inflow_30d_aed:,.0f} in 30 days is {x:.1f}x "
                          f"declared monthly income (soft {p['soft_ratio']}x, "
                          f"hard {p['hard_ratio']}x)"),
    )


def dormant_reactivation(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p = t["dormant_reactivation"]
    dormant = f.days_inactive_before_activity >= p["min_inactive_days"]
    x = f.inflow_vs_prior_ratio
    return TypologyFinding(
        typology="dormant_reactivation",
        score=ramp(x, p["soft_ratio"], p["hard_ratio"]) if dormant else 0.0,
        evidence_txn_ids=f.dormant_txn_ids,
        rule_explanation=(f"{f.days_inactive_before_activity} days without activity "
                          f"(needs {p['min_inactive_days']}), then 30-day inflow {x:.1f}x the "
                          f"prior monthly average (soft {p['soft_ratio']}x, "
                          f"hard {p['hard_ratio']}x)"),
    )


def high_risk_geo(f: Features, t: Mapping[str, Any]) -> TypologyFinding:
    p = t["high_risk_geo"]
    n = f.high_risk_txn_count
    where = ", ".join(f.high_risk_countries) or "none"
    return TypologyFinding(
        typology="high_risk_geo",
        score=ramp(n, p["soft_txns"], p["hard_txns"]),
        evidence_txn_ids=f.high_risk_txn_ids,
        rule_explanation=(f"{n} transactions with high-risk jurisdictions ({where}) "
                          f"(soft {p['soft_txns']}, hard {p['hard_txns']})"),
    )


RULES: dict[str, Callable[[Features, Mapping[str, Any]], TypologyFinding]] = {
    "structuring": structuring,
    "pass_through": pass_through,
    "funnel": funnel,
    "profile_mismatch": profile_mismatch,
    "dormant_reactivation": dormant_reactivation,
    "high_risk_geo": high_risk_geo,
}


def detect_typologies(f: Features, t: Mapping[str, Any] | None = None) -> list[TypologyFinding]:
    """All six findings, in a fixed order, including those that score 0."""
    t = t or load_thresholds()
    return [rule(f, t) for rule in RULES.values()]
