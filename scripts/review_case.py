"""Resume a paused case with the analyst's decision, then close its alert.

    uv run python scripts/review_case.py CASE-0001 --reviewer deepak --route escalate
    uv run python scripts/review_case.py CASE-0001 --reviewer deepak --route close \
        --reason "sale agreement seen on the shared drive"

Works in a fresh process: the case resumes from its Postgres checkpoint. Overriding the
recommended route needs --reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cases import close_alert  # noqa: E402
from app.graph.build import get_graph  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--route", required=True, choices=["close", "escalate", "needs_info"])
    ap.add_argument("--reason", help="required when overriding the recommended route")
    ap.add_argument("--edits")
    args = ap.parse_args()

    graph = get_graph()
    config = {"configurable": {"thread_id": args.case_id}}
    snapshot = graph.get_state(config)
    if snapshot.next != ("analyst_review",):
        sys.exit(f"{args.case_id} is not waiting for review (next: {snapshot.next or 'done'})")

    answer = {"reviewer": args.reviewer, "final_route": args.route,
              "override_reason": args.reason, "edits": args.edits}
    graph.invoke(Command(resume=answer), config)

    snapshot = graph.get_state(config)
    if snapshot.next:  # asked again: the answer was invalid
        for task in snapshot.tasks:
            for i in task.interrupts:
                sys.exit(f"Not accepted: {i.value.get('error')}")
    close_alert(args.case_id)
    state = snapshot.values
    print(f"{args.case_id}: recommended {state['route'].route}, "
          f"final {state['review'].final_route} by {state['review'].reviewer}\n")
    print(state["narrative"])
    if state.get("narrative_errors"):
        print("\nNarrative checks still failing:", *state["narrative_errors"], sep="\n- ")


if __name__ == "__main__":
    main()
