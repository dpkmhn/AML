"""Generate the synthetic bank end to end, from one seed.

    uv run python -m data.generator.generate --reset     # regenerate and reload Postgres
    uv run python -m data.generator.generate --no-db     # files in data/out only

Outputs (data/out): customers.csv, transactions.csv, alerts.csv, labels.jsonl. Labels never
go into the database the copilot reads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd

from app.rules.monitoring import run_monitoring
from data.generator.common import OUT_DIR, Ctx, Txn, load_config
from data.generator.customers import Customer, build_customers
from data.generator.inject import (
    TRAP_REFERENCES,
    TYPOLOGIES,
    TYPOLOGY_PLANTS,
    Plant,
    plant_injection_trap,
    plant_needs_info,
)
from data.generator.load import ALERT_COLS, CUSTOMER_COLS, TXN_COLS
from data.generator.lookalikes import LOOKALIKE_PLANTS
from data.generator.normal import assign_noise, generate_normal

DORMANT_WINDOW = (date(2026, 8, 15), date(2026, 9, 5))


# ---- who can carry which scenario ---------------------------------------------------------
def _segment_ok(c: Customer, kind: str, typology: str) -> bool:
    seg = c["segment"]
    no_rent = seg == "student" or (seg == "salaried" and not c["_pays_rent"])
    if typology == "dormant_reactivation":
        return seg == "salaried" and c["account_opened"] <= date(2025, 3, 1)
    if kind == "lookalike":
        return {
            "structuring": seg in ("business", "salaried", "retiree"),
            "pass_through": seg in ("salaried", "retiree", "business"),
            "funnel": (seg == "salaried" and not c["_pays_rent"]) or seg == "retiree",
            "profile_mismatch": seg in ("salaried", "retiree"),
            "high_risk_geo": seg in ("salaried", "retiree"),
        }[typology]
    if kind == "needs_info":
        return seg in ("salaried", "retiree", "student")
    return {  # typology and injection_trap
        "structuring": seg in ("salaried", "student"),
        "pass_through": seg in ("student", "salaried"),
        "funnel": no_rent and not c.get("_remits", False),
        "profile_mismatch": seg in ("salaried", "retiree", "student"),
        "high_risk_geo": seg in ("salaried", "business", "retiree"),
    }[typology]


def _pick(ctx: Ctx, customers: list[Customer], used: set[str], kind: str, typology: str,
          prefer: Any = None) -> Customer:
    def ok(c: Customer) -> bool:
        if c["customer_id"] in used or not _segment_ok(c, kind, typology):
            return False
        # Look-alikes and info cases must be closable: a high-risk customer escalates (R2).
        return kind not in ("lookalike", "needs_info") or (
            c["risk_rating"] != "high" and not c["is_pep"])

    pool = [c for c in customers if ok(c)]
    if prefer:
        preferred = [c for c in pool if prefer(c)]
        pool = preferred or pool
    if not pool:
        raise RuntimeError(f"no customer left for {kind}/{typology}")
    c = pool[int(ctx.rng.integers(len(pool)))]
    used.add(c["customer_id"])
    return c


def _start(ctx: Ctx, typology: str | None) -> date:
    if typology == "dormant_reactivation":
        return ctx.day_between(*DORMANT_WINDOW)
    sc = ctx.cfg["scenarios"]
    return ctx.day_between(date.fromisoformat(str(sc["window_start_min"])),
                           date.fromisoformat(str(sc["window_start_max"])))


def plant_scenarios(ctx: Ctx, customers: list[Customer]) -> list[tuple[str, Customer, Plant]]:
    sc, used = ctx.cfg["scenarios"], set()
    planted: list[tuple[str, Customer, Plant]] = []
    # Most constrained first: look-alikes need low/medium-risk customers of given segments.
    for typ in TYPOLOGIES:
        for i in range(sc["lookalike_per_type"]):
            prefer = None
            if typ == "structuring" and i < sc["lookalike_per_type"] // 2:
                prefer = lambda c: c.get("_cash_intensive", False)  # noqa: E731
            c = _pick(ctx, customers, used, "lookalike", typ, prefer)
            planted.append(("lookalike", c, LOOKALIKE_PLANTS[typ](ctx, c, _start(ctx, typ))))
    for _ in range(sc["needs_info"]):
        c = _pick(ctx, customers, used, "needs_info", "profile_mismatch")
        planted.append(("needs_info", c, plant_needs_info(ctx, c, _start(ctx, None))))
    for typ in TYPOLOGIES:
        for _ in range(sc["typology_per_type"]):
            c = _pick(ctx, customers, used, "typology", typ)
            planted.append(("typology", c, TYPOLOGY_PLANTS[typ](ctx, c, _start(ctx, typ))))
    for i in range(sc["injection_traps"]):
        typ = TYPOLOGIES[i % len(TYPOLOGIES)]
        c = _pick(ctx, customers, used, "injection_trap", typ)
        trap = TRAP_REFERENCES[i % len(TRAP_REFERENCES)]
        planted.append(("injection_trap", c,
                        plant_injection_trap(ctx, c, _start(ctx, typ), typ, trap)))
    return planted


# ---- assembly -------------------------------------------------------------------------------
def build(cfg: dict[str, Any]) -> dict[str, Any]:
    ctx = Ctx.create(cfg)
    customers = build_customers(ctx)
    planted = plant_scenarios(ctx, customers)
    assign_noise(ctx, customers, exclude={c["customer_id"] for _, c, _ in planted})
    txns: list[Txn] = generate_normal(ctx, customers)
    for _, _, p in planted:
        txns += p.txns

    tdf = pd.DataFrame(txns).sort_values(["ts", "customer_id", "_k"], kind="stable")
    tdf["txn_id"] = [f"TXN-{i:06d}" for i in range(1, len(tdf) + 1)]
    key_to_id = dict(zip(tdf["_k"], tdf["txn_id"], strict=True))
    tdf = tdf.reset_index(drop=True)

    cdf = pd.DataFrame(customers)
    alerts = run_monitoring(cdf, tdf, ctx.start, ctx.end)
    alerts["alert_id"] = [f"ALT-{i:04d}" for i in range(1, len(alerts) + 1)]
    # Monitoring runs overnight: alerts appear at 02:00 UTC the day after the window closes.
    alerts["created_at"] = [datetime.combine(d + timedelta(days=1), time(2), tzinfo=UTC)
                            for d in alerts["window_end"]]
    alerts["status"] = "open"

    labels = []
    for n, (kind, c, p) in enumerate(planted, start=1):
        start, end = p.window
        hit = alerts[(alerts.customer_id == c["customer_id"])
                     & (alerts.window_start <= end) & (alerts.window_end >= start)]
        labels.append({
            "scenario_id": f"SCN-{n:03d}",
            "customer_id": c["customer_id"],
            "kind": kind,
            "typology": p.typology,
            "expected_route": p.expected_route,
            "evidence_txn_ids": sorted(key_to_id[t["_k"]] for t in p.evidence),
            "window": [start.isoformat(), end.isoformat()],
            "notes": p.notes,
            **p.extra,
            "alert_ids": hit["alert_id"].tolist(),
            "alert_rules": hit["rule_id"].tolist(),
        })
    return {"customers": cdf, "transactions": tdf, "alerts": alerts, "labels": labels}


def write_outputs(data: dict[str, Any]) -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tdf = data["transactions"].copy()
    tdf["ts"] = pd.to_datetime(tdf["ts"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = data["alerts"].copy()
    alerts["created_at"] = pd.to_datetime(alerts["created_at"], utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    frames = {"customers.csv": data["customers"][CUSTOMER_COLS],
              "transactions.csv": tdf[TXN_COLS],
              "alerts.csv": alerts[ALERT_COLS]}
    hashes = {}
    for name, df in frames.items():
        text = df.to_csv(index=False, lineterminator="\n", float_format="%.2f")
        (OUT_DIR / name).write_text(text, encoding="utf-8")
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()[:16]
    lines = "".join(json.dumps(lbl) + "\n" for lbl in data["labels"])
    (OUT_DIR / "labels.jsonl").write_text(lines, encoding="utf-8")
    hashes["labels.jsonl"] = hashlib.sha256(lines.encode()).hexdigest()[:16]
    return hashes


def report(data: dict[str, Any], hashes: dict[str, str]) -> None:
    alerts, labels = data["alerts"], data["labels"]
    planted_alerts = {a for lbl in labels for a in lbl["alert_ids"]}
    noise = len(alerts) - len(planted_alerts)
    print(f"customers     {len(data['customers']):>6}")
    print(f"transactions  {len(data['transactions']):>6}")
    print(f"alerts        {len(alerts):>6}  (from planted scenarios {len(planted_alerts)}, "
          f"unplanted noise {noise} = {noise / max(len(alerts), 1):.0%})")
    print("alerts by rule ", alerts["rule_id"].value_counts().sort_index().to_dict())
    kinds = pd.Series([lbl["kind"] for lbl in labels]).value_counts().to_dict()
    print(f"scenarios     {len(labels):>6}  {kinds}")
    missed = [lbl for lbl in labels if not lbl["alert_ids"]]
    for lbl in missed:
        print(f"  NO ALERT: {lbl['scenario_id']} {lbl['kind']} {lbl['typology']} "
              f"{lbl['customer_id']} {lbl['window']}")
    if not missed:
        print("  every planted scenario raised at least one alert")
    print("hashes        ", hashes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="truncate tables before loading")
    ap.add_argument("--no-db", action="store_true", help="write data/out files only")
    args = ap.parse_args()

    data = build(load_config())
    hashes = write_outputs(data)
    report(data, hashes)
    if not args.no_db:
        from data.generator.load import load_all

        load_all(data["customers"], data["transactions"], data["alerts"], reset=args.reset)


if __name__ == "__main__":
    main()
