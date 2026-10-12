"""Draw the 60-alert golden set and write a review sheet for checking it by hand.

    uv run python -m data.build_golden            # refuses to overwrite a hand-checked file
    uv run python -m data.build_golden --force

Mix: 22 planted typologies, 28 close (20 benign look-alikes + 8 noise alerts), 6 needs more
info, 4 injection traps. Planted lines are pre-filled from labels.jsonl (first alert of each
scenario). Noise alerts have no ground truth: they are pre-filled as Close with
`needs_review: true`, and data/out/golden_review.md shows what you need to label them.

The hand-checked file differs from that draw: two noise alerts are labelled Needs more info
(ALT-0008 undocumented jump in cash deposits, ALT-0095 unexplained high-risk transfer), so the
final mix is 22 escalate, 26 close, 8 needs info, 4 traps.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data.generator.common import load_config
from data.local_data import LocalData

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.jsonl"
REVIEW_PATH = Path(__file__).resolve().parent / "out" / "golden_review.md"

TYPOLOGIES = ["structuring", "pass_through", "funnel", "profile_mismatch",
              "dormant_reactivation", "high_risk_geo"]
# Planted counts per typology, in TYPOLOGIES order
PLANTED_PER_TYPE = [4, 4, 4, 4, 3, 3]     # 22
LOOKALIKE_PER_TYPE = [4, 4, 3, 3, 3, 3]   # 20
N_TRAPS, N_NEEDS_INFO = 4, 6
NOISE_PER_RULE = {"TM-PM-01": 2, "TM-FUN-01": 2, "TM-PT-01": 2, "TM-STR-01": 1, "TM-GEO-01": 1}

RULE_TYPOLOGY = {"TM-STR-01": "structuring", "TM-PT-01": "pass_through", "TM-FUN-01": "funnel",
                 "TM-PM-01": "profile_mismatch", "TM-DOR-01": "dormant_reactivation",
                 "TM-GEO-01": "high_risk_geo"}
GROUP_OF_KIND = {"typology": "planted", "lookalike": "lookalike", "needs_info": "needs_info",
                 "injection_trap": "trap"}


def _sample(rng: np.random.Generator, items: list, n: int) -> list:
    if n > len(items):
        raise ValueError(f"need {n}, have {len(items)}")
    idx = sorted(rng.choice(len(items), size=n, replace=False).tolist())
    return [items[i] for i in idx]


def select(data: LocalData, seed: int) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    by_kind: dict[tuple[str, str | None], list[dict]] = {}
    for lbl in data.labels:
        by_kind.setdefault((lbl["kind"], lbl["typology"]), []).append(lbl)

    chosen: list[dict] = []
    for ty, n_planted, n_look in zip(TYPOLOGIES, PLANTED_PER_TYPE, LOOKALIKE_PER_TYPE,
                                     strict=True):
        chosen += _sample(rng, by_kind[("typology", ty)], n_planted)
        chosen += _sample(rng, by_kind[("lookalike", ty)], n_look)
    traps = [lbl for (kind, _), v in by_kind.items() if kind == "injection_trap" for lbl in v]
    chosen += _sample(rng, sorted(traps, key=lambda x: x["scenario_id"]), N_TRAPS)
    needs = [lbl for (kind, _), v in by_kind.items() if kind == "needs_info" for lbl in v]
    chosen += _sample(rng, sorted(needs, key=lambda x: x["scenario_id"]), N_NEEDS_INFO)

    lines = [_from_label(lbl, data) for lbl in chosen]
    lines += [_noise_line(a, data) for a in _noise_alerts(data, rng)]
    return sorted(lines, key=lambda x: x["alert_id"])


def _from_label(lbl: dict, data: LocalData) -> dict[str, Any]:
    alert_id = lbl["alert_ids"][0]
    group = GROUP_OF_KIND[lbl["kind"]]
    return {
        "alert_id": alert_id,
        "group": group,
        "expected_route": lbl["expected_route"],
        "typologies": [lbl["typology"]],
        "evidence_txn_ids": lbl["evidence_txn_ids"],
        "benign_reason": lbl.get("notes", "") if group == "lookalike" else "",
        "scenario_id": lbl["scenario_id"],
        "customer_id": lbl["customer_id"],
        "rule_id": data.alerts.loc[alert_id].rule_id,
        "notes": lbl.get("notes", "") if group != "lookalike" else "",
        "needs_review": False,
    }


def _noise_alerts(data: LocalData, rng: np.random.Generator) -> list[pd.Series]:
    """Alerts no scenario raised, from low and medium risk customers, stratified by rule.

    High-risk customers are left out so the 28-strong Close group stays intact: the bank's
    escalation criteria send any high-risk alert with a typology at 0.4 or above to level 2.
    """
    planted = {a for lbl in data.labels for a in lbl["alert_ids"]}
    risk = data.customers.risk_rating
    pool = data.alerts[~data.alerts.alert_id.isin(planted)
                       & (data.alerts.customer_id.map(risk) != "high")]
    out = []
    for rule_id, n in NOISE_PER_RULE.items():
        rows = [r for _, r in pool[pool.rule_id == rule_id].iterrows()]
        out += _sample(rng, rows, n)
    return out


def _noise_line(a: pd.Series, data: LocalData) -> dict[str, Any]:
    return {
        "alert_id": a.alert_id,
        "group": "noise",
        "expected_route": "close",
        "typologies": [RULE_TYPOLOGY[a.rule_id]],
        "evidence_txn_ids": [],
        "benign_reason": "",
        "scenario_id": None,
        "customer_id": a.customer_id,
        "rule_id": a.rule_id,
        "notes": "Noise alert: confirm route, typologies and benign reason by hand",
        "needs_review": True,
    }


# ---- review sheet ---------------------------------------------------------------------
def review_sheet(lines: list[dict], data: LocalData) -> str:
    md = ["# Golden set review", "",
          "Check every line in `data/golden_set.jsonl`. Planted lines come from the scenario "
          "labels; noise lines need a decision from you: route, typologies present, evidence "
          "transaction IDs and the benign reason. When done, set `needs_review` to false.", "",
          "## All 60 alerts", "",
          "| Alert | Group | Rule | Labelled typology | Score | Expected route | Note |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for g in lines:
        scores = {f.typology: f.score for f in data.findings(g["alert_id"])}
        ty = g["typologies"][0]
        md.append(f"| {g['alert_id']} | {g['group']} | {g['rule_id']} | {ty} | "
                  f"{scores[ty]:.2f} | {g['expected_route']} | "
                  f"{g['benign_reason'] or g['notes']} |")
    md += ["", "## Noise alerts in detail", ""]
    for g in (x for x in lines if x["group"] == "noise"):
        md += _noise_detail(g, data)
    return "\n".join(md) + "\n"


def _noise_detail(g: dict, data: LocalData) -> list[str]:
    c = data.profile(g["customer_id"])
    f = data.features(g["alert_id"])
    txns = data.txns_by_customer[g["customer_id"]]
    ts = pd.to_datetime(txns.ts, utc=True).dt.date
    window = txns[(ts >= f.review_start) & (ts <= f.review_end) & (txns.channel != "card")]
    top = window.sort_values("amount_aed", ascending=False).head(12)
    md = [f"### {g['alert_id']} · {g['rule_id']} · {c['full_name']} ({g['customer_id']})", "",
          f"- **Profile:** {c['segment']}, {c['occupation']}, declared income "
          f"AED {c['declared_monthly_income_aed']:,.0f}/month, risk {c['risk_rating']}",
          f"- **Expected activity:** {c['expected_activity']}",
          f"- **KYC notes:** {c['kyc_notes']}",
          f"- **Review window:** {f.review_start} to {f.review_end}; inflow "
          f"AED {f.inflow_aed:,.0f}, outflow AED {f.outflow_aed:,.0f}; baseline inflow "
          f"AED {f.baseline_monthly_inflow_aed:,.0f}/month", "",
          "| Typology | Score | Rule |", "| --- | --- | --- |"]
    md += [f"| {x.typology} | {x.score:.2f} | {x.rule_explanation} |"
           for x in data.findings(g["alert_id"])]
    md += ["", "Largest non-card transactions in the review window:", "",
           "| Txn | Date | AED | Dir | Channel | Counterparty | Country | Reference |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for _, t in top.iterrows():
        md.append(f"| {t.txn_id} | {str(t.ts)[:10]} | {t.amount_aed:,.0f} | {t.direction} | "
                  f"{t.channel} | {_cell(t.counterparty_name)} | "
                  f"{_cell(t.counterparty_country)} | {_cell(t.reference)} |")
    return md + [""]


def _cell(v: Any) -> str:
    return "" if pd.isna(v) else str(v).replace("|", "/")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="overwrite an existing golden set")
    args = ap.parse_args()
    if GOLDEN_PATH.exists() and not args.force:
        raise SystemExit(f"{GOLDEN_PATH.name} exists and may hold hand edits; use --force")

    data = LocalData()
    lines = select(data, load_config()["seed"])
    GOLDEN_PATH.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    REVIEW_PATH.write_text(review_sheet(lines, data), encoding="utf-8")

    counts = pd.Series([x["group"] for x in lines]).value_counts().to_dict()
    print(f"Wrote {len(lines)} alerts to {GOLDEN_PATH.relative_to(Path.cwd())}: {counts}")
    print(f"Review sheet: {REVIEW_PATH.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
