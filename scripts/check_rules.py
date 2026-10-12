"""Run the six typology rules on the golden alerts (no database, no LLM).

    uv run python scripts/check_rules.py

Phase 2 exit gate: the labelled typology scores 0.4 or more in at least 20 of 22 planted cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.build_golden import GOLDEN_PATH, RULE_TYPOLOGY  # noqa: E402
from data.local_data import LocalData  # noqa: E402

GATE_DETECTED, GATE_PLANTED = 20, 22


def main() -> None:
    data = LocalData()
    golden = [json.loads(x) for x in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if x]
    fired_at = data.thresholds["routing"]["high_risk_escalate_score"]

    rows = []
    for g in golden:
        found = {f.typology: f for f in data.findings(g["alert_id"])}
        # A noise alert with no typology present is scored on the rule that raised it.
        ty = g["typologies"][0] if g["typologies"] else RULE_TYPOLOGY[g["rule_id"]]
        ev, got = set(g["evidence_txn_ids"]), set(found[ty].evidence_txn_ids)
        rows.append({
            "alert": g["alert_id"], "group": g["group"], "route": g["expected_route"],
            "typology": ty,
            "score": found[ty].score,
            "detected": found[ty].score >= fired_at,
            "evidence_recall": len(ev & got) / len(ev) if ev else None,
            "also_fired": ", ".join(f"{k} {v.score:.2f}" for k, v in found.items()
                                    if k != ty and v.score >= fired_at),
        })
    df = pd.DataFrame(rows)

    pd.set_option("display.width", 160)
    summary = df.groupby("group").agg(
        alerts=("alert", "size"), detected=("detected", "sum"), mean_score=("score", "mean"),
        evidence_recall=("evidence_recall", "mean"))
    print("Labelled typology by group (detected = score >= "
          f"{fired_at})\n{summary.round(2).to_string()}\n")

    print("Per typology, planted and trap cases")
    esc = df[df.group.isin(["planted", "trap"])]
    print(esc.groupby("typology").agg(alerts=("alert", "size"), detected=("detected", "sum"),
                                      min_score=("score", "min")).round(2).to_string(), "\n")

    print("Noise alerts (hand-labelled)")
    print(df[df.group == "noise"][["alert", "route", "typology", "score", "also_fired"]]
          .to_string(index=False), "\n")

    missed = df[(df.group == "planted") & ~df.detected]
    if len(missed):
        print("Missed planted cases\n" + missed.to_string(index=False) + "\n")

    detected = int(df[df.group == "planted"].detected.sum())
    planted = int((df.group == "planted").sum())
    ok = planted == GATE_PLANTED and detected >= GATE_DETECTED
    print(f"Exit gate: {detected} of {planted} planted cases detected "
          f"(needs {GATE_DETECTED} of {GATE_PLANTED}): {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
