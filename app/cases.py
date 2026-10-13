"""Starting a case: code outside the graph creates the cases row and moves the alert status.

The case_id is also the LangGraph thread_id, so a case and its checkpoint share one key.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db import session


def start_case(alert_id: str) -> str:
    """The alert's case, created on first use; the alert moves to in_review."""
    with session("rw") as s:
        case_id = s.execute(text("SELECT case_id FROM cases WHERE alert_id = :a"),
                            {"a": alert_id}).scalar_one_or_none()
        if case_id is None:
            n = s.execute(text(
                "SELECT coalesce(max(substring(case_id FROM 6)::int), 0) + 1 FROM cases"
            )).scalar_one()
            case_id = f"CASE-{n:04d}"
            s.execute(text("INSERT INTO cases (case_id, alert_id) VALUES (:c, :a)"),
                      {"c": case_id, "a": alert_id})
        s.execute(text("UPDATE alerts SET status = 'in_review' "
                       "WHERE alert_id = :a AND status = 'open'"), {"a": alert_id})
    return case_id


def set_recommended_route(case_id: str, route: str) -> None:
    with session("rw") as s:
        s.execute(text("UPDATE cases SET recommended_route = :r WHERE case_id = :c"),
                  {"r": route, "c": case_id})


def save_decision(case_id: str, *, recommended_route: str, final_route: str, reviewer: str,
                  override_reason: str | None, pack: dict[str, Any], narrative: str) -> None:
    with session("rw") as s:
        s.execute(text("""
            UPDATE cases
            SET recommended_route = :rec, final_route = :final, reviewer = :reviewer,
                override_reason = :reason, pack = CAST(:pack AS jsonb), narrative = :narrative,
                decided_at = now()
            WHERE case_id = :c
        """), {"rec": recommended_route, "final": final_route, "reviewer": reviewer,
               "reason": override_reason, "pack": json.dumps(pack), "narrative": narrative,
               "c": case_id})


def close_alert(case_id: str) -> None:
    """After write_audit: the case has a final route, so the alert is closed."""
    with session("rw") as s:
        s.execute(text("""
            UPDATE alerts SET status = 'closed'
            WHERE alert_id = (SELECT alert_id FROM cases
                              WHERE case_id = :c AND final_route IS NOT NULL)
        """), {"c": case_id})
