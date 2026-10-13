"""The analyst decision, the narrative checks and the narrative node's retry."""

import pytest
from pydantic import ValidationError

from app.graph.nodes.review import INTERNAL, check_narrative
from app.schemas import AnalystDecision
from tests.conftest import NARRATIVE


def decide(context=None, **kw):
    return AnalystDecision.model_validate({"reviewer": "deepak", **kw}, context=context)


def test_agreeing_needs_no_reason():
    assert decide({"recommended": "escalate"}, final_route="escalate").override_reason is None


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_override_needs_a_reason(reason):
    with pytest.raises(ValidationError, match="override_reason is required"):
        decide({"recommended": "escalate"}, final_route="close", override_reason=reason)


def test_override_with_reason_is_accepted():
    d = decide({"recommended": "needs_info"}, final_route="close", override_reason="docs seen")
    assert d.final_route == "close"


def test_reviewer_is_required():
    with pytest.raises(ValidationError):
        AnalystDecision.model_validate({"reviewer": "", "final_route": "close"})


KNOWN = {"txn_ids": {"TXN-000001"}, "chunk_ids": {"CHK-TYP-STR-05"}}


def test_narrative_with_known_ids_and_all_headings_passes():
    text = NARRATIVE.replace("See the pack.", "Deposit [TXN-000001] per [CHK-TYP-STR-05].")
    assert check_narrative(text, **KNOWN) == []


def test_narrative_with_unknown_ids_fails():
    errors = check_narrative(NARRATIVE + "\n[TXN-123456] [CHK-TYP-PT-02]", **KNOWN)
    assert "TXN-123456" in errors[0] and "CHK-TYP-PT-02" in errors[1]


def test_narrative_missing_a_heading_fails():
    errors = check_narrative(NARRATIVE.replace("Checks performed", "Checks"), **KNOWN)
    assert "Checks performed" in errors[0]


def test_markdown_headings_are_accepted():
    text = "\n".join(f"## {line}" if line and "." not in line else line
                     for line in NARRATIVE.splitlines())
    assert check_narrative(text, **KNOWN) == []


def test_narrative_is_retried_once_and_marked_internal(offline):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from app.graph.build import build_graph, checkpoint_serde

    offline.llm.narratives = ["no headings at all", NARRATIVE]
    graph = build_graph(InMemorySaver(serde=checkpoint_serde()))
    cfg = {"configurable": {"thread_id": "CASE-0001"}}
    graph.invoke({"case_id": "CASE-0001", "alert_id": "ALT-0042"}, cfg)
    route = graph.get_state(cfg).values["route"].route
    graph.invoke(Command(resume={"reviewer": "deepak", "final_route": route}), cfg)
    s = graph.get_state(cfg).values
    completes = [c for c in offline.llm.calls if c["kind"] == "complete"]
    assert len(completes) == 2
    assert "Missing headings" in completes[1]["messages"][-1]["content"]
    assert s["narrative"] == f"{INTERNAL}.\n\n{NARRATIVE}"
    assert s["narrative_errors"] == []
    # the narrative is written from the analyst's decision
    assert '"final_route": "' + route + '"' in completes[0]["messages"][1]["content"]
