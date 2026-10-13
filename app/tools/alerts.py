"""get_alert and list_alerts: alert rows, read through the copilot_ro role."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text

from app.db import session
from app.schemas import Alert

AlertStatus = Literal["open", "in_review", "closed"]

_SQL = text("""
SELECT alert_id, customer_id, rule_id, window_start, window_end, created_at, status
FROM alerts
WHERE alert_id = :alert_id
""")


def get_alert(alert_id: str) -> Alert:
    with session("ro") as s:
        row = s.execute(_SQL, {"alert_id": alert_id}).mappings().one_or_none()
    if row is None:
        raise LookupError(f"no alert {alert_id}")
    return Alert.model_validate(dict(row))


_LIST_SQL = """
SELECT a.alert_id, a.customer_id, c.full_name AS customer_name, a.rule_id, a.window_start,
       a.window_end, a.created_at, a.status
FROM alerts a JOIN customers c USING (customer_id)
{where}
ORDER BY a.created_at, a.alert_id
"""


def list_alerts(status: AlertStatus | None = None) -> list[dict]:
    """Alerts with the customer's name, oldest first; all statuses when status is None."""
    where = "WHERE a.status = :status" if status else ""
    with session("ro") as s:
        rows = s.execute(text(_LIST_SQL.format(where=where)), {"status": status}).mappings()
        return [dict(r) for r in rows]
