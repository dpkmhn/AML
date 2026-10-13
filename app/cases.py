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
        case_id = s.execute(text("SELECT case_id FROM cases "
                                 "WHERE alert_id = :a AND kind = 'case'"),
                            {"a": alert_id}).scalar_one_or_none()
        if case_id is None:
            n = s.execute(text(
                "SELECT coalesce(max(substring(case_id FROM 6)::int), 0) + 1 FROM cases "
                "WHERE kind = 'case'"
            )).scalar_one()
            case_id = f"CASE-{n:04d}"
            s.execute(text("INSERT INTO cases (case_id, alert_id) VALUES (:c, :a)"),
                      {"c": case_id, "a": alert_id})
        s.execute(text("UPDATE alerts SET status = 'in_review' "
                       "WHERE alert_id = :a AND status = 'open'"), {"a": alert_id})
    return case_id


def start_eval_case(case_id: str, alert_id: str) -> str:
    """An evaluation case: its own row (kind 'eval') so the audit log can point at it; the
    alert's status is left alone."""
    with session("rw") as s:
        s.execute(text("INSERT INTO cases (case_id, alert_id, kind) VALUES (:c, :a, 'eval') "
                       "ON CONFLICT (case_id) DO NOTHING"), {"c": case_id, "a": alert_id})
    return case_id


def get_case(case_id: str) -> dict[str, Any] | None:
    """The cases row, or None. Evaluation cases are not served."""
    with session("rw") as s:
        row = s.execute(text("SELECT * FROM cases WHERE case_id = :c AND kind = 'case'"),
                        {"c": case_id}).mappings().one_or_none()
    return dict(row) if row else None


def case_routes() -> dict[str, dict[str, Any]]:
    """alert_id -> case_id and routes, for every real case (the queue's sort key)."""
    with session("rw") as s:
        rows = s.execute(text("SELECT alert_id, case_id, recommended_route, final_route "
                              "FROM cases WHERE kind = 'case'")).mappings().all()
    return {r["alert_id"]: dict(r) for r in rows}


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
