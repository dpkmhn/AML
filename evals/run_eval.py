"""Run the golden set through the case graph and score the recommendation.

    uv run python -m evals.run_eval --tag baseline
    uv run python -m evals.run_eval --tag strong --model strong
    uv run python -m evals.run_eval --tag nofilter --rag-filter off --no-judge
    uv run python -m evals.run_eval --tag smoke --alerts ALT-0008 ALT-0023

Each alert gets a fresh thread (EVAL-<run>-<alert>, a cases row of kind 'eval') and runs
until the analyst_review interrupt, where the recommendation is read. The JUDGE_SAMPLE
alerts are then resumed with the recommended route so a narrative is drafted and judged.

Writes evals/results/<date>_<tag>.json (every case, every field) and adds a row and a
confusion matrix to evals/results/summary.md. Flags change one thing from the reference
configuration (small model, quoted references, filtered retrieval, rules decide).
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langgraph.types import Command
from sqlalchemy import text

from app.audit import jsonable
from app.cases import start_eval_case
from app.config import settings
from app.db import session
from app.graph.build import NODES, get_graph
from app.schemas import RunConfig
from app.validate import TXN_ID
from data.build_golden import GOLDEN_PATH
from evals import metrics
from evals.judge import JUDGE_SAMPLE, JUDGE_VERSION, judge

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
SUMMARY = RESULTS / "summary.md"
HAND_SCORES = EVALS / "notes" / "hand_scores.csv"
PRE_REVIEW = [name for name, _ in NODES][:[name for name, _ in NODES].index("analyst_review")]


def load_golden() -> list[dict[str, Any]]:
    return [json.loads(x) for x in GOLDEN_PATH.read_text("utf-8").splitlines() if x]


def load_prices() -> dict[str, dict[str, float]]:
    return yaml.safe_load((EVALS / "prices.yaml").read_text("utf-8"))["models"]


def usage_by_step(case_id: str) -> list[dict[str, Any]]:
    with session("rw") as s:
        rows = s.execute(text(
            "SELECT step, model, coalesce(tokens_in, 0) AS tokens_in, "
            "coalesce(tokens_out, 0) AS tokens_out, latency_ms FROM audit_log "
            "WHERE case_id = :c ORDER BY id"), {"c": case_id}).mappings().all()
    return [dict(r) for r in rows]


def cost(rows: list[dict[str, Any]], prices: dict[str, dict[str, float]]) -> float:
    total = 0.0
    for r in rows:
        if r["model"]:
            p = prices[r["model"]]  # a model missing from prices.yaml is an error
            total += (r["tokens_in"] * p["input"] + r["tokens_out"] * p["output"]) / 1e6
    return total


def cited(state: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """Transaction IDs and guidance chunks the assessment cites."""
    a = state.get("assessment")
    if a is None:
        return [], []
    txn_ids = {i for b in a.benign_explanations for i in b.evidence_txn_ids}
    for t in [a.activity_summary, *a.concerns, *(b.explanation for b in a.benign_explanations)]:
        txn_ids |= set(TXN_ID.findall(t))
    chunk_ids = set(a.cited_chunk_ids) | {i for b in a.benign_explanations
                                          for i in b.cited_chunk_ids}
    typology = {c.chunk_id: c.typology for c in state.get("guidance", [])}
    chunks = [{"chunk_id": i, "typology": typology.get(i, "unknown")} for i in sorted(chunk_ids)]
    return sorted(txn_ids), chunks


def run_case(g: dict[str, Any], run_id: str, cfg: RunConfig, do_judge: bool,
             prices: dict[str, dict[str, float]]) -> dict[str, Any]:
    case_id = f"EVAL-{run_id}-{g['alert_id']}"
    out: dict[str, Any] = {
        "alert_id": g["alert_id"], "case_id": case_id, "group": g["group"],
        "expected_route": g["expected_route"], "golden_typologies": g["typologies"],
        "golden_evidence": g["evidence_txn_ids"], "benign_reason": g["benign_reason"],
        "route": None, "fired_typologies": [], "cited_txn_ids": [], "cited_chunks": [],
        "cost_usd": 0.0, "latency_s": None, "error": None}
    graph = get_graph()
    config = {"configurable": {"thread_id": case_id}}
    try:
        start_eval_case(case_id, g["alert_id"])
        t0 = time.perf_counter()
        graph.invoke({"case_id": case_id, "alert_id": g["alert_id"], "run_config": cfg}, config)
        out["latency_s"] = round(time.perf_counter() - t0, 2)
        state = graph.get_state(config).values
        route, a = state["route"], state["assessment"]
        txn_ids, chunks = cited(state)
        out.update({
            "route": route.route, "rule_ids": route.rule_ids, "route_reasons": route.reasons,
            "fired_typologies": route.fired_typologies,
            "explained_typologies": route.explained_typologies,
            "findings": [{"typology": f.typology, "score": f.score} for f in state["findings"]],
            "confidence": a.confidence, "assessment": jsonable(a),
            "assessment_errors": state.get("assessment_errors", []),
            "flagged_txn_ids": state.get("flagged_txn_ids", []),
            "guidance": [{"chunk_id": c.chunk_id, "typology": c.typology}
                         for c in state.get("guidance", [])],
            "cited_txn_ids": txn_ids, "cited_chunks": chunks})
        rows = usage_by_step(case_id)
        pre = [r for r in rows if r["step"] in PRE_REVIEW]
        out["steps"] = pre
        out["tokens_in"] = sum(r["tokens_in"] for r in pre)
        out["tokens_out"] = sum(r["tokens_out"] for r in pre)
        out["cost_usd"] = round(cost(pre, prices), 6)

        if do_judge and g["alert_id"] in JUDGE_SAMPLE:
            graph.invoke(Command(resume={"reviewer": "eval", "final_route": route.route}),
                         config)
            state = graph.get_state(config).values
            score, usage = judge(state)
            narr = [r for r in usage_by_step(case_id) if r["step"] == "draft_narrative"]
            out.update({"narrative": state["narrative"],
                        "narrative_errors": state.get("narrative_errors", []),
                        "narrative_cost_usd": round(cost(narr, prices), 6),
                        "judge": score,
                        "judge_cost_usd": round(cost([{
                            "model": settings.model_strong, "tokens_in": usage.tokens_in,
                            "tokens_out": usage.tokens_out}], prices), 6)})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()
    return out


# --- summary ---------------------------------------------------------------------------------

HEADER = ("| Run | Prompt | Model | Config | Missed esc. | Route acc. | False esc. | Evidence acc. "
          "| Citation acc. | Injection | Cost/alert | p50 / p95 s | Errors |\n"
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
SKELETON = f"""# Evaluation results

Generated by `evals/run_eval.py`: each run adds a row and a confusion matrix. Missed esc. =
golden Escalate routed to Close; False esc. = golden Close routed to Escalate; Injection =
traps not routed to Escalate. Evidence acc. = cited transaction IDs in the labelled evidence;
Citation acc. = cited typology chunks matching a golden typology (general chunks left out).
Cost and latency cover the case up to the analyst review.

## Runs

<!-- runs -->
{HEADER}
<!-- /runs -->

## Confusion matrices

Rows are the golden route, columns the recommended route.

<!-- matrices -->
<!-- /matrices -->
"""


def pct(hits: int, total: int) -> str:
    return f"{hits / total:.0%} ({hits}/{total})" if total else "n/a"


def summary_row(run: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    c = run["config"]
    flags = [f"route={c['route_mode']}"]
    if not c["use_filter"]:
        flags.append("rag-filter off")
    if not c["use_guard"]:
        flags.append("references raw")
    inj, traps = metrics.injection_failures(cases)
    mean, _ = metrics.cost_per_alert(cases)
    p50, p95 = metrics.latency(cases)
    errors = sum(x["error"] is not None for x in cases)
    return (f"| {run['run_id']} {run['tag']} | v{c['prompt_version']} | {c['model']} "
            f"| {', '.join(flags)} | {len(metrics.missed_escalations(cases))} "
            f"| {pct(*metrics.route_accuracy(cases))} | {len(metrics.false_escalations(cases))} "
            f"| {pct(*metrics.evidence_accuracy(cases))} "
            f"| {pct(*metrics.citation_accuracy(cases))} | {len(inj)} of {traps} "
            f"| ${mean:.4f} | {p50:.1f} / {p95:.1f} | {errors} |")


def update_summary(run: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    doc = SUMMARY.read_text("utf-8") if SUMMARY.exists() else SKELETON
    doc = doc.replace("<!-- /runs -->", summary_row(run, cases) + "\n<!-- /runs -->", 1)
    matrix = (f"### {run['run_id']} {run['tag']}\n\n```\n"
              f"{metrics.format_confusion(metrics.confusion(cases))}\n```\n\n")
    doc = doc.replace("<!-- /matrices -->", matrix + "<!-- /matrices -->", 1)
    SUMMARY.write_text(doc, "utf-8", newline="\n")


def report(cases: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    inj, traps = metrics.injection_failures(cases)
    mean, p95c = metrics.cost_per_alert(cases)
    p50, p95 = metrics.latency(cases)
    return {
        "missed_escalations": metrics.missed_escalations(cases),
        "false_escalations": metrics.false_escalations(cases),
        "route_accuracy": metrics.route_accuracy(cases),
        "evidence_accuracy": metrics.evidence_accuracy(cases),
        "evidence_recall": metrics.evidence_recall(cases),
        "citation_accuracy": metrics.citation_accuracy(cases),
        "injection_failures": inj, "traps": traps,
        "typology_detection": metrics.typology_detection(cases),
        "low_confidence": metrics.low_confidence(cases),
        "confusion": metrics.confusion(cases).tolist(),
        "cost_mean_usd": mean, "cost_p95_usd": p95c, "latency_p50_s": p50, "latency_p95_s": p95,
        "judge_agreement": metrics.judge_agreement(
            cases, metrics.load_hand_scores(HAND_SCORES, run_id)),
        "errors": [x["alert_id"] for x in cases if x["error"]],
    }


def print_report(r: dict[str, Any], cases: list[dict[str, Any]]) -> None:
    print(f"\nRoute accuracy      {pct(*r['route_accuracy'])}")
    print(f"Missed escalations  {len(r['missed_escalations'])} {r['missed_escalations']}")
    print(f"False escalations   {len(r['false_escalations'])} {r['false_escalations']}")
    print(f"Injection failures  {len(r['injection_failures'])} of {r['traps']}")
    print(f"Evidence accuracy   {pct(*r['evidence_accuracy'])}; "
          f"recall {pct(*r['evidence_recall'])}")
    print(f"Citation accuracy   {pct(*r['citation_accuracy'])}")
    print(f"Cost/alert          ${r['cost_mean_usd']:.4f} mean, ${r['cost_p95_usd']:.4f} p95")
    print(f"Latency             {r['latency_p50_s']:.1f}s p50, {r['latency_p95_s']:.1f}s p95")
    print(f"Low confidence      {len(r['low_confidence'])}")
    print(f"\n{metrics.format_confusion(metrics.confusion(cases))}\n")
    for ty, d in r["typology_detection"].items():
        print(f"  {ty:<22} precision {d['precision']:.2f}  recall {d['recall']:.2f}  "
              f"(tp {d['tp']}, fp {d['fp']}, fn {d['fn']})")
    print("\nMisrouted:")
    for c in metrics.misrouted(cases):
        why = c["error"] or "; ".join(c.get("route_reasons", []))
        print(f"  {c['alert_id']} {c['group']:<10} {c['expected_route']:>10} -> "
              f"{c['route']!s:<10} {why[:110]}")
    judged = [c for c in cases if c.get("judge")]
    if judged:
        print(f"\nJudge on {len(judged)} narratives: mean "
              f"{sum(c['judge'].get('total', 0) for c in judged) / len(judged):.1f}/5, "
              f"faithful {sum(bool(c['judge'].get('faithful')) for c in judged)}"
              f"/{len(judged)}; agreement with hand scores: {r['judge_agreement']}")
    if r["errors"]:
        print(f"\nErrors: {r['errors']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="short run name, e.g. baseline")
    ap.add_argument("--summarize", type=Path, metavar="RESULTS_JSON",
                    help="add a saved run to summary.md instead of running (for parallel runs)")
    ap.add_argument("--model", choices=["small", "strong"], default="small",
                    help="model for assess_case and draft_narrative")
    ap.add_argument("--route-mode", choices=["rules", "llm"], default="rules",
                    help="who picks the route: the routing rules or the model")
    ap.add_argument("--rag-filter", choices=["on", "off"], default="on")
    ap.add_argument("--references", choices=["quoted", "raw"], default="quoted")
    ap.add_argument("--alerts", nargs="+", help="only these golden alerts")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-judge", action="store_true", help="skip narratives and the judge")
    ap.add_argument("--no-summary", action="store_true", help="do not touch summary.md")
    args = ap.parse_args()

    if args.summarize:
        saved = json.loads(args.summarize.read_text("utf-8"))
        update_summary(saved["run"], saved["cases"])
        print(f"Added {saved['run']['run_id']} {saved['run']['tag']} to {SUMMARY}")
        return
    if not args.tag:
        ap.error("--tag is required")
    golden = load_golden()
    if args.alerts:
        golden = [g for g in golden if g["alert_id"] in set(args.alerts)]
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%d%H%M%S")  # also in thread IDs: parallel runs must differ
    cfg = RunConfig(model=settings.model_strong if args.model == "strong" else settings.model_small,
                    prompt_version=settings.prompt_version, use_filter=args.rag_filter == "on",
                    use_guard=args.references == "quoted", route_mode=args.route_mode)
    prices = load_prices()
    get_graph()  # build once, before the threads share it
    print(f"run {run_id} {args.tag}: {len(golden)} alerts, {cfg.model}, prompt "
          f"v{cfg.prompt_version}, filter {args.rag_filter}, references {args.references}, "
          f"route {args.route_mode}")

    def one(g: dict[str, Any]) -> dict[str, Any]:
        r = run_case(g, run_id, cfg, not args.no_judge, prices)
        mark = "ok " if r["route"] == r["expected_route"] else "ERR" if r["error"] else "-- "
        print(f"  {mark} {r['alert_id']} {r['group']:<10} {r['expected_route']:>10} -> "
              f"{r['route']!s:<10} {r['latency_s'] or 0:>5.1f}s ${r['cost_usd']:.4f}"
              + (f"  {r['error'][:120]}" if r["error"] else ""), flush=True)
        return r

    with ThreadPoolExecutor(args.workers) as pool:
        cases = sorted(pool.map(one, golden), key=lambda c: c["alert_id"])

    run = {"run_id": run_id, "tag": args.tag, "started": now.isoformat(),
           "config": {**cfg.model_dump(), "judge_version": JUDGE_VERSION},
           "prices_checked": str(yaml.safe_load((EVALS / "prices.yaml").read_text())["checked"])}
    r = report(cases, run_id)
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{now:%Y-%m-%d}_{args.tag}.json"
    if path.exists():
        path = path.with_stem(f"{path.stem}_{run_id}")
    path.write_text(json.dumps({"run": run, "metrics": r, "cases": cases}, indent=1,
                               default=str), "utf-8")
    print_report(r, cases)
    if not args.no_summary:
        update_summary(run, cases)
    print(f"\nWrote {path.relative_to(EVALS.parent)}"
          + ("" if args.no_summary else f" and {SUMMARY.relative_to(EVALS.parent)}"))


if __name__ == "__main__":
    main()
