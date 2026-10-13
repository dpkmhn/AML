"""get_transactions: one customer's transactions over a date range, read through copilot_ro."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text

from app.db import session
from app.schemas import Txn

_SQL = text("""
SELECT txn_id, customer_id, ts, amount_aed, direction, channel,
       counterparty_id, counterparty_name, counterparty_country, reference
FROM transactions
WHERE customer_id = :customer_id AND ts >= :start_ts AND ts < :end_ts
ORDER BY ts, txn_id
""")


def get_transactions(customer_id: str, start: date, end: date,
                     baseline_days: int = 90) -> list[Txn]:
    """Transactions from `baseline_days` before `start` to the end of `end` (UTC days).

    The caller sets `baseline_days` to cover the history its features need: dormancy looks
    back further than the 90-day baseline.
    """
    start_ts = datetime.combine(start - timedelta(days=baseline_days), time.min, UTC)
    end_ts = datetime.combine(end + timedelta(days=1), time.min, UTC)
    with session("ro") as s:
        rows = s.execute(_SQL, {"customer_id": customer_id, "start_ts": start_ts,
                                "end_ts": end_ts}).mappings().all()
    return [Txn.model_validate(dict(r)) for r in rows]
