"""get_alert: one alert row, read through the copilot_ro role."""

from __future__ import annotations

from sqlalchemy import text

from app.db import session
from app.schemas import Alert

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
