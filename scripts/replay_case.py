"""Print a case's full audit trail: every step with its model, prompt version and tokens.

    uv run python scripts/replay_case.py CASE-0007 [--all-runs] [--output]

By default shows the latest run (from its last load_alert row); --output adds each step's
recorded output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("--all-runs", action="store_true")
    ap.add_argument("--output", action="store_true")
    args = ap.parse_args()

    with session("rw") as s:
        case = s.execute(text("SELECT * FROM cases WHERE case_id = :c"),
                         {"c": args.case_id}).mappings().one_or_none()
        if case is None:
            sys.exit(f"no case {args.case_id}")
        rows = s.execute(text("SELECT * FROM audit_log WHERE case_id = :c ORDER BY id"),
                         {"c": args.case_id}).mappings().all()
    if not args.all_runs:
        starts = [i for i, r in enumerate(rows) if r["step"] == "load_alert"]
        rows = rows[starts[-1]:] if starts else rows

    print(f"{case['case_id']}  alert {case['alert_id']}  recommended {case['recommended_route']}"
          f"  final {case['final_route']}  reviewer {case['reviewer']}"
          f"  decided {case['decided_at']}")
    if case["override_reason"]:
        print(f"override reason: {case['override_reason']}")
    print(f"\n{'#':>2}  {'step':<18} {'at (UTC)':<19} {'ms':>6}  {'model':<14} "
          f"{'prompt':<18} {'in':>6} {'out':>5}")
    for n, r in enumerate(rows, 1):
        print(f"{n:>2}  {r['step']:<18} {r['created_at']:%Y-%m-%d %H:%M:%S} "
              f"{r['latency_ms']:>6}  {r['model'] or '-':<14} {r['prompt_version'] or '-':<18} "
              f"{r['tokens_in'] or '-':>6} {r['tokens_out'] or '-':>5}")
        if args.output:
            print("    " + json.dumps(r["output"], ensure_ascii=False)[:600])
    total_in = sum(r["tokens_in"] or 0 for r in rows)
    total_out = sum(r["tokens_out"] or 0 for r in rows)
    print(f"\n{len(rows)} steps, {total_in} tokens in, {total_out} tokens out")
    if case["narrative"]:
        print(f"\n{case['narrative']}")


if __name__ == "__main__":
    main()
