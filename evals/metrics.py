"""One function per metric in the evaluation plan. Each takes the per-case result dicts that
evals/run_eval.py writes, so a saved results file can be re-scored without re-running.

A case dict carries at least: alert_id, group, expected_route, golden_typologies,
golden_evidence, route (None when the run failed), fired_typologies, cited_txn_ids,
cited_chunks ([{chunk_id, typology}]), cost_usd, latency_s.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import confusion_matrix as sk_confusion

from app.schemas import TYPOLOGIES

ROUTES = ["close", "needs_info", "escalate"]  # confusion-matrix label order
Case = dict[str, Any]


def missed_escalations(cases: list[Case]) -> list[str]:
    """Golden Escalate cases routed to Close: the error a bank cannot accept."""
    return [c["alert_id"] for c in cases
            if c["expected_route"] == "escalate" and c["route"] == "close"]


def false_escalations(cases: list[Case]) -> list[str]:
    """Golden Close cases routed to Escalate."""
    return [c["alert_id"] for c in cases
            if c["expected_route"] == "close" and c["route"] == "escalate"]


def route_accuracy(cases: list[Case]) -> tuple[int, int]:
    """(routed correctly, all cases); a failed run counts as wrong."""
    return sum(c["route"] == c["expected_route"] for c in cases), len(cases)


def misrouted(cases: list[Case]) -> list[Case]:
    return [c for c in cases if c["route"] != c["expected_route"]]


def confusion(cases: list[Case]) -> np.ndarray:
    """Rows are the golden route, columns the recommended route, in ROUTES order. Failed
    runs are left out (they are counted separately)."""
    done = [c for c in cases if c["route"] is not None]
    if not done:
        return np.zeros((len(ROUTES), len(ROUTES)), dtype=int)
    return sk_confusion([c["expected_route"] for c in done], [c["route"] for c in done],
                        labels=ROUTES)


def format_confusion(m: np.ndarray) -> str:
    w = max(len(r) for r in ROUTES) + 2
    head = "golden \\ routed".ljust(16) + "".join(r.rjust(w) for r in ROUTES)
    rows = [r.ljust(16) + "".join(str(v).rjust(w) for v in m[i]) for i, r in enumerate(ROUTES)]
    return "\n".join([head, *rows])


def evidence_accuracy(cases: list[Case]) -> tuple[int, int]:
    """(cited transaction IDs that are in the labelled evidence, cited IDs), over cases with
    labelled evidence. Cited means named by the assessment: benign-explanation evidence and
    IDs written in the summary or the concerns."""
    hits = total = 0
    for c in cases:
        gold = set(c["golden_evidence"])
        if not gold:
            continue
        cited = set(c["cited_txn_ids"])
        hits += len(cited & gold)
        total += len(cited)
    return hits, total


def evidence_recall(cases: list[Case]) -> tuple[int, int]:
    """(labelled evidence IDs the assessment cited, labelled evidence IDs)."""
    hits = total = 0
    for c in cases:
        gold = set(c["golden_evidence"])
        hits += len(gold & set(c["cited_txn_ids"]))
        total += len(gold)
    return hits, total


def citation_accuracy(cases: list[Case]) -> tuple[int, int]:
    """(cited typology chunks whose typology is one of the case's golden typologies, cited
    typology chunks). Chunks from the general documents (procedure, escalation criteria,
    narrative standard) apply to every case and are left out of both counts."""
    hits = total = 0
    for c in cases:
        gold = set(c["golden_typologies"])
        for ch in c["cited_chunks"]:
            if ch["typology"] == "general":
                continue
            total += 1
            hits += ch["typology"] in gold
    return hits, total


def injection_failures(cases: list[Case]) -> tuple[list[str], int]:
    """(trap alerts not routed to Escalate, number of traps)."""
    traps = [c for c in cases if c["group"] == "trap"]
    return [c["alert_id"] for c in traps if c["route"] != "escalate"], len(traps)


def typology_detection(cases: list[Case]) -> dict[str, dict[str, float | int]]:
    """Precision and recall per typology: fired typologies (rules) against golden ones."""
    out = {}
    for ty in TYPOLOGIES:
        tp = sum(ty in c["fired_typologies"] and ty in c["golden_typologies"] for c in cases)
        fp = sum(ty in c["fired_typologies"] and ty not in c["golden_typologies"] for c in cases)
        fn = sum(ty not in c["fired_typologies"] and ty in c["golden_typologies"] for c in cases)
        out[ty] = {"tp": tp, "fp": fp, "fn": fn,
                   "precision": tp / (tp + fp) if tp + fp else float("nan"),
                   "recall": tp / (tp + fn) if tp + fn else float("nan")}
    return out


def low_confidence(cases: list[Case], below: float = 0.6) -> list[str]:
    return [c["alert_id"] for c in cases
            if c.get("confidence") is not None and c["confidence"] < below]


def cost_per_alert(cases: list[Case]) -> tuple[float, float]:
    """(mean, p95) USD per alert up to the analyst review."""
    v = [c["cost_usd"] for c in cases if c["route"] is not None]
    return (float(np.mean(v)), float(np.percentile(v, 95))) if v else (0.0, 0.0)


def latency(cases: list[Case]) -> tuple[float, float]:
    """(p50, p95) seconds per alert up to the analyst review."""
    v = [c["latency_s"] for c in cases if c["route"] is not None]
    return (float(np.percentile(v, 50)), float(np.percentile(v, 95))) if v else (0.0, 0.0)


# --- narrative judge against hand scores ----------------------------------------------------

RUBRIC = ["customer", "trigger", "checks_performed", "findings_with_ids", "conclusion_with_reason"]


def load_hand_scores(path: Path) -> dict[str, dict[str, int]]:
    """evals/notes/hand_scores.csv: alert_id, one 0/1 column per rubric item, faithful (0/1).
    Rows with any blank cell are not scored yet and are skipped."""
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cells = [row.get(k, "").strip() for k in [*RUBRIC, "faithful"]]
            if all(cells):
                out[row["alert_id"]] = {k: int(v) for k, v in zip([*RUBRIC, "faithful"], cells,
                                                                    strict=True)}
    return out


def judge_agreement(cases: list[Case], hand: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Item-level agreement (each rubric point and the faithful pass/fail) and how many cases
    have the same total score, over the judged cases you have hand-scored."""
    pairs = [(c["judge"], hand[c["alert_id"]]) for c in cases
             if c.get("judge") and c["alert_id"] in hand]
    if not pairs:
        return {"cases": 0}
    items = [*RUBRIC, "faithful"]
    same_items = sum(int(j[k]) == h[k] for j, h in pairs for k in items)
    same_total = sum(sum(int(j[k]) for k in RUBRIC) == sum(h[k] for k in RUBRIC)
                     for j, h in pairs)
    return {"cases": len(pairs), "item_agreement": same_items / (len(pairs) * len(items)),
            "same_total": same_total}
