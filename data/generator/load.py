"""Bulk-load generated rows into Postgres with COPY (psycopg 3)."""

from __future__ import annotations

import pandas as pd
import psycopg

from app.config import settings

CUSTOMER_COLS = ["customer_id", "full_name", "segment", "occupation",
                 "declared_monthly_income_aed", "expected_activity", "risk_rating", "is_pep",
                 "nationality", "account_opened", "kyc_notes"]
TXN_COLS = ["txn_id", "customer_id", "ts", "amount_aed", "direction", "channel",
            "counterparty_id", "counterparty_name", "counterparty_country", "reference"]
ALERT_COLS = ["alert_id", "customer_id", "rule_id", "window_start", "window_end", "created_at",
              "status"]


def _conninfo() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://")


def _copy(cur: psycopg.Cursor, table: str, df: pd.DataFrame, cols: list[str]) -> None:
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as copy:
        for row in df[cols].itertuples(index=False, name=None):
            copy.write_row([None if pd.isna(v) else v for v in row])


def load_all(customers: pd.DataFrame, txns: pd.DataFrame, alerts: pd.DataFrame,
             reset: bool) -> None:
    with psycopg.connect(_conninfo()) as conn, conn.cursor() as cur:
        if reset:
            cur.execute("TRUNCATE audit_log, cases, alerts, transactions, customers CASCADE")
        else:
            cur.execute("SELECT count(*) FROM customers")
            if cur.fetchone()[0]:
                raise SystemExit("customers is not empty; rerun with --reset to replace the data")
        _copy(cur, "customers", customers, CUSTOMER_COLS)
        _copy(cur, "transactions", txns, TXN_COLS)
        _copy(cur, "alerts", alerts, ALERT_COLS)
        conn.commit()
        for table in ("customers", "transactions", "alerts"):
            cur.execute(f"SELECT count(*) FROM {table}")
            print(f"  loaded {table:<13} {cur.fetchone()[0]:>6}")
