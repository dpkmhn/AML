"""Load the generated data from data/out CSVs and run the deterministic rules on one alert.

No database needed; used by the golden-set builder and the rule checks. The copilot itself
reads the same rows from Postgres through the read-only tools (stage 3.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd

from app.rules.features import compute_features
from app.rules.monitoring import load_thresholds
from app.rules.typologies import detect_typologies
from app.schemas import Features, TypologyFinding

OUT = Path(__file__).resolve().parent / "out"


@dataclass
class LocalData:
    out: Path = OUT

    @cached_property
    def customers(self) -> pd.DataFrame:
        return pd.read_csv(self.out / "customers.csv").set_index("customer_id", drop=False)

    @cached_property
    def alerts(self) -> pd.DataFrame:
        return pd.read_csv(self.out / "alerts.csv").set_index("alert_id", drop=False)

    @cached_property
    def txns_by_customer(self) -> dict[str, pd.DataFrame]:
        txns = pd.read_csv(self.out / "transactions.csv")
        return dict(tuple(txns.groupby("customer_id")))

    @cached_property
    def labels(self) -> list[dict[str, Any]]:
        lines = (self.out / "labels.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    @cached_property
    def thresholds(self) -> dict[str, Any]:
        return load_thresholds()

    def profile(self, customer_id: str) -> dict[str, Any]:
        return self.customers.loc[customer_id].to_dict()

    def features(self, alert_id: str) -> Features:
        a = self.alerts.loc[alert_id]
        return compute_features(self.profile(a.customer_id), self.txns_by_customer[a.customer_id],
                                date.fromisoformat(a.window_start),
                                date.fromisoformat(a.window_end), self.thresholds)

    def findings(self, alert_id: str) -> list[TypologyFinding]:
        return detect_typologies(self.features(alert_id), self.thresholds)
