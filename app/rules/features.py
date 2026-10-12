"""compute_features: the numbers the typology rules score, each with its transaction IDs.

Pure functions over one customer's transactions (a DataFrame with the `transactions` table's
columns). No database and no LLM, so every number is reproducible and unit-testable.

Pass enough history for dormancy to show: at least `min_inactive_days` plus the baseline
before the review window. With less, a long silence cannot be told apart from missing data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.rules.monitoring import load_thresholds
from app.schemas import Features

_HOUR_NS = 3_600_000_000_000


def review_window(window_start: date, window_end: date, t: Mapping[str, Any]) -> tuple[date, date]:
    """The alert window extended by the review lag: what an analyst sees on review day."""
    return window_start, window_end + timedelta(days=t["features"]["review_lag_days"])


class _Account:
    """One customer's transactions as sorted arrays; day slices via searchsorted."""

    def __init__(self, txns: pd.DataFrame):
        df = txns.sort_values(["ts", "txn_id"], kind="stable")
        ts = pd.to_datetime(df["ts"], utc=True).dt.as_unit("ns")
        self.ids = df["txn_id"].to_numpy()
        self.ts = ts.astype("int64").to_numpy()
        self.day = np.array([d.toordinal() for d in ts.dt.date], dtype=np.int64)
        self.amount = df["amount_aed"].astype(float).to_numpy()
        self.is_in = (df["direction"] == "in").to_numpy()
        self.cash = (df["channel"] == "cash").to_numpy()
        self.card = (df["channel"] == "card").to_numpy()
        self.transfer = (df["channel"] == "transfer").to_numpy()
        self.cp = df["counterparty_id"].fillna("").to_numpy()
        self.country = df["counterparty_country"].fillna("").to_numpy()

    def span(self, start: date, end: date) -> slice:
        """Index range of transactions on days start..end inclusive."""
        lo = int(self.day.searchsorted(start.toordinal(), side="left"))
        hi = int(self.day.searchsorted(end.toordinal(), side="right"))
        return slice(lo, hi)


def _best_window(a: _Account, review: slice, review_start: date, days: int,
                 key: Callable[[slice], Any]) -> slice:
    """The `days`-long span inside the review window that maximises `key`.

    Candidate spans end on each day with activity; ties keep the earliest span.
    """
    best, best_key = slice(review.start, review.start), None
    for end_ord in sorted(set(a.day[review].tolist())):
        end = date.fromordinal(end_ord)
        start = max(end - timedelta(days=days - 1), review_start)
        s = a.span(start, end)
        k = key(s)
        if best_key is None or k > best_key:
            best, best_key = s, k
    return best


def _ids(a: _Account, idx: np.ndarray | slice, mask: np.ndarray | None = None) -> list[str]:
    ids = a.ids[idx]
    return [str(i) for i in (ids if mask is None else ids[mask])]


def compute_features(profile: Mapping[str, Any], txns: pd.DataFrame, window_start: date,
                     window_end: date, t: Mapping[str, Any] | None = None) -> Features:
    t = t or load_thresholds()
    income = float(profile["declared_monthly_income_aed"])
    review_start, review_end = review_window(window_start, window_end, t)
    baseline_days = t["features"]["baseline_days"]
    baseline_start = review_start - timedelta(days=baseline_days)

    a = _Account(txns)
    r = a.span(review_start, review_end)
    base = a.span(baseline_start, review_start - timedelta(days=1))

    amt, inn = a.amount[r], a.is_in[r]
    inflow, outflow = float(amt[inn].sum()), float(amt[~inn].sum())
    total = float(amt.sum())

    return Features(
        customer_id=str(profile["customer_id"]),
        review_start=review_start,
        review_end=review_end,
        baseline_start=baseline_start,
        txn_count=int(r.stop - r.start),
        inflow_aed=round(inflow, 2),
        outflow_aed=round(outflow, 2),
        in_out_ratio=round(inflow / outflow, 3) if outflow else None,
        cash_share=round(float(amt[a.cash[r]].sum()) / total, 3) if total else 0.0,
        max_single_txn_aed=round(float(amt.max()), 2) if len(amt) else 0.0,
        baseline_monthly_inflow_aed=round(
            float(a.amount[base][a.is_in[base]].sum()) / (baseline_days / 30), 2),
        **_structuring(a, r, review_start, t),
        **_pass_through(a, r, review_start, t),
        **_funnel(a, r, review_start, t),
        **_profile_mismatch(a, r, base, review_start, income, t),
        **_dormant(a, r, review_end, t),
        **_high_risk_geo(a, r, t),
    )


def _structuring(a: _Account, r: slice, review_start: date, t: Mapping) -> dict:
    p, thr = t["structuring"], t["cash_reporting_threshold_aed"]
    band = a.is_in & a.cash & (a.amount >= p["band_low"] * thr) & (a.amount < thr)
    s = _best_window(a, r, review_start, p["window_days"], lambda s: int(band[s].sum()))
    return {"cash_near_threshold_count": int(band[s].sum()),
            "cash_near_threshold_txn_ids": _ids(a, s, band[s])}


def _pass_through(a: _Account, r: slice, review_start: date, t: Mapping) -> dict:
    """An event: a large inflow with at least `outflow_share` of it sent out (by transfer or
    cash) within `max_hours`. Each outflow counts towards one event only."""
    p = t["pass_through"]
    horizon = p["max_hours"] * _HOUR_NS
    out_ok = ~a.is_in & ~a.card
    used = np.zeros(len(a.ids), dtype=bool)
    event_at = np.zeros(len(a.ids), dtype=bool)  # marks the inflow of each event
    members: dict[int, list[int]] = {}
    for i in range(r.start, r.stop):
        if not (a.is_in[i] and a.amount[i] >= p["min_inflow_aed"]):
            continue
        j_end = int(a.ts.searchsorted(a.ts[i] + horizon, side="right"))
        legs = [j for j in range(i + 1, j_end) if out_ok[j] and not used[j]]
        if a.amount[legs].sum() >= p["outflow_share"] * a.amount[i]:
            used[legs] = True
            event_at[i] = True
            members[i] = legs
    s = _best_window(a, r, review_start, p["window_days"], lambda s: int(event_at[s].sum()))
    ids: list[str] = []
    for i in range(s.start, s.stop):
        if event_at[i]:
            ids += [str(a.ids[i])] + [str(a.ids[j]) for j in members[i]]
    return {"pass_through_events": int(event_at[s].sum()), "pass_through_txn_ids": ids}


def _funnel(a: _Account, r: slice, review_start: date, t: Mapping) -> dict:
    p = t["funnel"]
    tin, tout = a.transfer & a.is_in, a.transfer & ~a.is_in

    def counts(s: slice) -> tuple[int, int]:
        return len(set(a.cp[s][tin[s]])), len(set(a.cp[s][tout[s]]))

    def key(s: slice) -> tuple[bool, int]:
        senders, receivers = counts(s)
        return 1 <= receivers <= p["max_receivers"], senders

    s = _best_window(a, r, review_start, p["window_days"], key)
    senders, receivers = counts(s)
    qualifies = 1 <= receivers <= p["max_receivers"]
    return {"distinct_senders": senders, "distinct_receivers": receivers,
            "funnel_txn_ids": _ids(a, s, a.transfer[s]) if qualifies else []}


def _profile_mismatch(a: _Account, r: slice, base: slice, review_start: date, income: float,
                      t: Mapping) -> dict:
    """Best 30-day inflow against declared income. Evidence is the new money: inflows from
    counterparties not seen in the baseline (cash counts as new), largest first."""
    s = _best_window(a, r, review_start, 30, lambda s: float(a.amount[s][a.is_in[s]].sum()))
    inflow = float(a.amount[s][a.is_in[s]].sum())
    known = set(a.cp[base]) - {""}
    idx = [i for i in range(s.start, s.stop) if a.is_in[i] and a.cp[i] not in known]
    if not idx:
        idx = [i for i in range(s.start, s.stop) if a.is_in[i]]
    idx = sorted(idx, key=lambda i: -a.amount[i])
    # keep the inflows that make up 90% of the new money
    keep, running, target = [], 0.0, 0.9 * float(a.amount[idx].sum()) if idx else 0.0
    for i in idx:
        if running >= target and keep:
            break
        keep.append(i)
        running += a.amount[i]
    return {"max_inflow_30d_aed": round(inflow, 2),
            "inflow_to_income_ratio": round(inflow / income, 3) if income > 0 else 0.0,
            "profile_mismatch_txn_ids": [str(a.ids[i]) for i in sorted(keep)]}


def _dormant(a: _Account, r: slice, review_end: date, t: Mapping) -> dict:
    """The longest silence before any transaction in the review window, and the inflow in the
    30 days after it against the average monthly inflow before it."""
    p = t["dormant_reactivation"]
    empty = {"days_inactive_before_activity": 0, "inflow_vs_prior_ratio": 0.0,
             "dormant_txn_ids": []}
    first = max(r.start, 1)  # the very first transaction on record has no silence before it
    if first >= r.stop:
        return empty
    gaps = a.day[first:r.stop] - a.day[first - 1:r.stop - 1]
    k = first + int(gaps.argmax())
    gap = int(a.day[k] - a.day[k - 1])
    hist = slice(0, k)
    span_days = max(int(a.day[k - 1] - a.day[0]), 30)
    prior_monthly = float(a.amount[hist][a.is_in[hist]].sum()) / (span_days / 30)
    start = date.fromordinal(int(a.day[k]))
    s = a.span(start, min(start + timedelta(days=29), review_end))
    inflow = float(a.amount[s][a.is_in[s]].sum())
    ratio = inflow / prior_monthly if prior_monthly > 0 else (999.0 if inflow > 0 else 0.0)
    ids = _ids(a, s, ~a.card[s]) if gap >= p["min_inactive_days"] else []
    return {"days_inactive_before_activity": gap, "inflow_vs_prior_ratio": round(ratio, 3),
            "dormant_txn_ids": ids}


def _high_risk_geo(a: _Account, r: slice, t: Mapping) -> dict:
    countries = set(t["high_risk_geo"]["countries"])
    mask = np.isin(a.country[r], list(countries))
    return {"high_risk_txn_count": int(mask.sum()),
            "high_risk_countries": sorted(set(a.country[r][mask].tolist())),
            "high_risk_txn_ids": _ids(a, r, mask)}
