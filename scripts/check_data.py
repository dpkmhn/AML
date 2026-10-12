"""Sanity checks on the generated data in data/out (no database needed).

    uv run python scripts/check_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "out"


def main() -> None:
    cust = pd.read_csv(OUT / "customers.csv")
    txns = pd.read_csv(OUT / "transactions.csv", parse_dates=["ts"])
    alerts = pd.read_csv(OUT / "alerts.csv")
    labels = [json.loads(line) for line in (OUT / "labels.jsonl").read_text().splitlines()]

    print("Customers by segment and risk")
    print(pd.crosstab(cust.segment, cust.risk_rating, margins=True), "\n")
    print(f"PEPs: {int(cust.is_pep.sum())} (all high risk: "
          f"{bool((cust[cust.is_pep].risk_rating == 'high').all())})\n")

    t = txns.merge(cust[["customer_id", "segment", "declared_monthly_income_aed"]],
                   on="customer_id")
    t = t[t.ts >= "2026-04-01"]
    t["month"] = t.ts.dt.strftime("%Y-%m")
    inflow = t[t.direction == "in"].groupby(["segment", "month"]).amount_aed.sum().unstack()
    per_cust = inflow.div(cust.segment.value_counts(), axis=0)
    print("Mean monthly inflow per customer (AED)")
    print(per_cust.round(0).to_string(), "\n")
    declared = cust.groupby("segment").declared_monthly_income_aed.mean().round(0)
    print("Mean declared monthly income (AED)")
    print(declared.to_string(), "\n")

    print("Transactions per customer per month by segment")
    counts = t.groupby(["segment", "month"]).size().unstack()
    print(counts.div(cust.segment.value_counts(), axis=0).round(1).to_string(), "\n")

    print("Channel x direction")
    print(pd.crosstab(txns.channel, txns.direction), "\n")

    planted = {a for lbl in labels for a in lbl["alert_ids"]}
    alerts["source"] = alerts.alert_id.map(lambda a: "planted" if a in planted else "noise")
    print("Alerts by rule and source")
    print(pd.crosstab(alerts.rule_id, alerts.source, margins=True), "\n")

    kinds = pd.DataFrame(labels).groupby(["kind", "expected_route"]).size()
    print("Scenarios by kind and expected route")
    print(kinds.to_string())


if __name__ == "__main__":
    main()
