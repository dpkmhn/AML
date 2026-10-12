"""Transaction monitoring: six loose rules over 30-day sliding windows.

This stands in for the bank's existing monitoring engine. It is broad on purpose, so it raises
realistic false positives for the copilot to clear. Thresholds live in thresholds.yaml.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

THRESHOLDS_PATH = Path(__file__).with_name("thresholds.yaml")

RULE_IDS = ["TM-STR-01", "TM-PT-01", "TM-FUN-01", "TM-PM-01", "TM-DOR-01", "TM-GEO-01"]

_HOUR_NS = 3_600_000_000_000


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class _Account:
    """One customer's transactions as sorted numpy arrays, sliced by day with searchsorted."""

    def __init__(self, txns: pd.DataFrame, income: float, high_risk: set[str]):
        df = txns.sort_values("ts", kind="stable")
        ts = pd.to_datetime(df["ts"], utc=True).dt.as_unit("ns")
        self.ts = ts.astype("int64").to_numpy()  # nanoseconds since epoch
        self.day = np.array([d.toordinal() for d in ts.dt.date])
        self.amount = df["amount_aed"].astype(float).to_numpy()
        self.is_in = (df["direction"] == "in").to_numpy()
        self.cash = (df["channel"] == "cash").to_numpy()
        self.transfer = (df["channel"] == "transfer").to_numpy()
        self.cp = df["counterparty_id"].fillna("").to_numpy()
        self.geo = df["counterparty_country"].isin(high_risk).to_numpy()
        self.income = income

    def span(self, start: date, end: date) -> slice:
        lo = int(self.day.searchsorted(start.toordinal(), side="left"))
        hi = int(self.day.searchsorted(end.toordinal(), side="right"))
        return slice(lo, hi)


Rule = Callable[[_Account, date, date, dict[str, Any], dict[str, Any]], bool]


def _structuring(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    thr = t["cash_reporting_threshold_aed"]
    s = a.span(end - timedelta(days=p["lookback_days"] - 1), end)
    amt = a.amount[s]
    band = a.is_in[s] & a.cash[s] & (amt >= p["band_low"] * thr) & (amt < thr)
    return int(band.sum()) >= p["min_count"]


def _pass_through(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    s = a.span(start, end)
    big_in = np.flatnonzero(a.is_in[s] & a.transfer[s] & (a.amount[s] >= p["min_inflow_aed"]))
    if len(big_in) < p["min_events"]:
        return False
    ts, amt, out = a.ts[s], a.amount[s], ~a.is_in[s]
    horizon = p["max_hours"] * _HOUR_NS
    events = 0
    for i in big_in:
        j = int(ts.searchsorted(ts[i] + horizon, side="right"))
        sent = amt[i + 1 : j][out[i + 1 : j]].sum()
        events += sent >= p["outflow_share"] * amt[i]
    return events >= p["min_events"]


def _funnel(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    s = a.span(start, end)
    tr, inn, cp = a.transfer[s], a.is_in[s], a.cp[s]
    senders = len(set(cp[tr & inn]))
    if senders < p["min_senders"]:
        return False
    receivers = len(set(cp[tr & ~inn]))
    return 1 <= receivers <= p["max_receivers"]


def _profile_mismatch(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    s = a.span(start, end)
    inflow = a.amount[s][a.is_in[s]].sum()
    return a.income > 0 and inflow > p["min_ratio"] * a.income


def _dormant(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    s = a.span(start, end)
    if s.start == s.stop or s.start == 0:
        return False
    gap = a.day[s.start] - a.day[s.start - 1]
    if gap < p["min_inactive_days"]:
        return False
    hist = slice(0, s.start)
    span_days = max(int(a.day[s.start - 1] - a.day[0]), 30)
    prior_monthly = a.amount[hist][a.is_in[hist]].sum() / (span_days / 30)
    inflow = a.amount[s][a.is_in[s]].sum()
    return prior_monthly > 0 and inflow >= p["min_ratio"] * prior_monthly


def _high_risk_geo(a: _Account, start: date, end: date, p: dict, t: dict) -> bool:
    s = a.span(start, end)
    return int(a.geo[s].sum()) >= p["min_txns"]


RULES: dict[str, Rule] = {
    "TM-STR-01": _structuring,
    "TM-PT-01": _pass_through,
    "TM-FUN-01": _funnel,
    "TM-PM-01": _profile_mismatch,
    "TM-DOR-01": _dormant,
    "TM-GEO-01": _high_risk_geo,
}


def run_monitoring(customers: pd.DataFrame, txns: pd.DataFrame, monitor_start: date,
                   monitor_end: date, thresholds: dict[str, Any] | None = None) -> pd.DataFrame:
    """Return alerts (customer_id, rule_id, window_start, window_end), sorted, without IDs.

    Windows are evaluated at the end of each day the customer transacted. A rule fires on the
    first day its condition holds, then stays quiet for that customer for `rule_suppress_days`.
    Hits on one customer within `consolidate_days` of each other become one alert, recorded
    under the most specific rule that fired.
    """
    t = thresholds or load_thresholds()
    mon = t["monitoring"]
    span = timedelta(days=mon["window_days"] - 1)
    first_end = (monitor_start + span).toordinal()
    income = customers.set_index("customer_id")["declared_monthly_income_aed"].astype(float)
    high_risk = set(mon["high_risk_countries"])

    rows: list[dict[str, Any]] = []
    for cid, g in txns.groupby("customer_id", sort=True):
        hits: list[dict[str, Any]] = []
        acc = _Account(g, float(income[cid]), high_risk)
        days = sorted({int(d) for d in acc.day if first_end <= d <= monitor_end.toordinal()})
        for rule_id in RULE_IDS:
            rule, params = RULES[rule_id], mon[rule_id]
            quiet_until = 0
            for d in days:
                if d < quiet_until:
                    continue
                end = date.fromordinal(d)
                start = end - span
                if rule(acc, start, end, params, t):
                    hits.append({"customer_id": cid, "rule_id": rule_id,
                                 "window_start": start, "window_end": end})
                    quiet_until = d + mon["rule_suppress_days"]
        rows += _consolidate(hits, mon["rule_priority"], mon["consolidate_days"])
    alerts = pd.DataFrame(rows, columns=["customer_id", "rule_id", "window_start", "window_end"])
    return alerts.sort_values(["window_end", "customer_id", "rule_id"]).reset_index(drop=True)


def _consolidate(hits: list[dict[str, Any]], priority: list[str],
                 days: int) -> list[dict[str, Any]]:
    """Group one customer's hits that end within `days` of the group's first hit."""
    rank = {r: i for i, r in enumerate(priority)}
    hits = sorted(hits, key=lambda h: (h["window_end"], rank[h["rule_id"]]))
    out = []
    while hits:
        horizon = hits[0]["window_end"] + timedelta(days=days)
        group = [h for h in hits if h["window_end"] < horizon]
        hits = hits[len(group):]
        out.append(min(group, key=lambda h: (rank[h["rule_id"]], h["window_end"])))
    return out
