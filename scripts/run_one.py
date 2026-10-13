"""Run one alert through the case graph and print what each node added to the state.

    uv run python scripts/run_one.py ALT-0042

The run stops at analyst_review; resume it with scripts/review_case.py. Needs Postgres with
the data and guidance loaded, and OPENAI_API_KEY. The case is created on first use and reused
after that; each run starts the graph again from the first node on the same thread.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cases import start_case  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import session  # noqa: E402
from app.graph.build import get_graph  # noqa: E402
from app.schemas import RunConfig  # noqa: E402


def show(node: str, update: dict[str, Any] | None) -> None:
    print(f"\n== {node}")
    if not update:
        print("   (no change)")
        return
    for key, value in update.items():
        if key == "alert":
            print(f"   alert     {value.alert_id} {value.rule_id} {value.customer_id} "
                  f"{value.window_start}..{value.window_end}")
        elif key == "profile":
            print(f"   profile   {value.full_name}, {value.segment}, {value.occupation}; "
                  f"income AED {value.declared_monthly_income_aed:,.0f}/month; "
                  f"risk {value.risk_rating}{', PEP' if value.is_pep else ''}")
            print(f"   kyc_notes {value.kyc_notes}")
        elif key == "txns":
            print(f"   txns      {len(value)} transactions "
                  f"({value[0].ts:%Y-%m-%d} to {value[-1].ts:%Y-%m-%d})" if value else "   txns 0")
        elif key == "features":
            for name, v in value.model_dump().items():
                if isinstance(v, list) and len(v) > 6:
                    v = f"{v[:6]} ... ({len(v)} ids)"
                print(f"   {name:<30} {v}")
        elif key == "findings":
            for f in value:
                print(f"   {f.typology:<22} {f.score:.2f}  {f.rule_explanation}")
        elif key == "guidance":
            for c in value:
                print(f"   {c.chunk_id:<18} {c.similarity or 0:.3f}  {c.typology} / {c.section}")
        elif key == "assessment":
            print(textwrap.indent(value.model_dump_json(indent=2), "   "))
        elif key == "route":
            print(f"   {value.route} ({', '.join(value.rule_ids)})")
            for r in value.reasons:
                print(f"     - {r}")
        else:
            print(f"   {key}: {value}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("alert_id")
    args = ap.parse_args()

    case_id = start_case(args.alert_id)
    started = datetime.now(UTC)
    print(f"{args.alert_id} -> {case_id} (thread_id)")

    run_config = RunConfig(model=settings.model_small, prompt_version=settings.prompt_version)
    inputs = {"case_id": case_id, "alert_id": args.alert_id, "run_config": run_config}
    config = {"configurable": {"thread_id": case_id}}
    for chunk in get_graph().stream(inputs, config, stream_mode="updates"):
        for node, update in chunk.items():
            if node == "__interrupt__":  # the pause: a tuple of Interrupts, not a state update
                request = update[0].value
                print(f"\n== analyst_review\n   paused for the analyst: recommended "
                      f"{request['recommended_route']}")
                for f in request["pack"]["flagged_references"]:
                    print(f"   flagged {f['txn_id']}: {f['reference']!r} ({f['note']})")
            else:
                show(node, update)

    with session("rw") as s:
        rows = s.execute(text(
            "SELECT step, latency_ms, model, tokens_in, tokens_out FROM audit_log "
            "WHERE case_id = :c AND created_at >= :t ORDER BY id"),
            {"c": case_id, "t": started}).all()
    print(f"\naudit_log: {len(rows)} rows for {case_id} in this run")
    for r in rows:
        print(f"   {r.step:<18} {r.latency_ms:>6} ms  {r.model or ''}")

    if get_graph().get_state(config).next:
        print(f"\nResume with: uv run python scripts/review_case.py {case_id} "
              f"--reviewer <name> --route <close|escalate|needs_info> [--reason ...]")


if __name__ == "__main__":
    main()
