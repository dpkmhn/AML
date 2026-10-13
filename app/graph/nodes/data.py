"""Nodes that read the case's data through the read-only tools.

The alert decides which customer and which dates are read; nothing here takes a value
chosen by the model.
"""

from __future__ import annotations

from app.audit import audited
from app.graph.state import CaseState
from app.rules.features import review_window
from app.rules.monitoring import load_thresholds
from app.tools import alerts, profile, transactions


@audited("load_alert")
def load_alert(state: CaseState) -> CaseState:
    return {"alert": alerts.get_alert(state["alert_id"])}


@audited("get_profile")
def get_profile(state: CaseState) -> CaseState:
    return {"profile": profile.get_profile(state["alert"].customer_id)}


@audited("get_transactions")
def get_transactions(state: CaseState) -> CaseState:
    a, t = state["alert"], load_thresholds()
    start, end = review_window(a.window_start, a.window_end, t)
    # history_days covers both the baseline and the dormancy look-back
    txns = transactions.get_transactions(a.customer_id, start, end,
                                         baseline_days=t["history_days"])
    return {"txns": txns}
