"""Narrative judge: MODEL_STRONG scores a drafted narrative against the case facts.

Only the JUDGE_SAMPLE cases are judged; run_eval.py resumes them with the recommended route
so draft_narrative runs, then calls judge(). Score the same cases by hand in
evals/notes/hand_scores.csv and run_eval.py reports the agreement.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app import llm
from app.config import settings
from app.graph.nodes.review import narrative_message
from app.graph.state import CaseState
from app.prompts import load_prompt
from data.build_golden import GOLDEN_PATH

JUDGE_PROMPT = "judge_narrative"
JUDGE_VERSION = 1
# a fixed stratified sample: the first alerts of each golden group, 15 in all
PER_GROUP = {"planted": 5, "lookalike": 4, "noise": 2, "needs_info": 2, "trap": 2}


def judge_sample() -> list[str]:
    rows = [json.loads(x) for x in GOLDEN_PATH.read_text("utf-8").splitlines() if x]
    out = []
    for group, n in PER_GROUP.items():
        out += sorted(r["alert_id"] for r in rows if r["group"] == group)[:n]
    return sorted(out)


JUDGE_SAMPLE = judge_sample()


class NarrativeScore(BaseModel):
    customer: bool
    trigger: bool
    checks_performed: bool
    findings_with_ids: bool
    conclusion_with_reason: bool
    unsupported_facts: list[str]
    faithful: bool


def judge(state: CaseState) -> tuple[dict, llm.Usage]:
    """The score as a dict with a 0-5 total, and the token usage of the judge call."""
    messages = [{"role": "system", "content": load_prompt(JUDGE_PROMPT, JUDGE_VERSION)},
                {"role": "user", "content": f"{narrative_message(state)}\n\n"
                                            f"## Narrative to score\n{state['narrative']}"}]
    parsed, raw, usage = llm.parse(settings.model_strong, messages, NarrativeScore)
    if parsed is None:
        return {"error": raw}, usage
    score = parsed.model_dump()
    score["total"] = sum(score[k] for k in ("customer", "trigger", "checks_performed",
                                            "findings_with_ids", "conclusion_with_reason"))
    return score, usage
