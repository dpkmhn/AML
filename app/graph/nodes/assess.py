"""assess_case: the one LLM call that shapes the route, and only through the facts it returns.

The model gets the profile, the rule findings, the retrieved guidance and the transactions
(references quoted as untrusted data). Its CaseAssessment is post-checked in code; failures
go back to it once with the error list, and a second failure sets confidence to 0, which
routes to Needs more info.
"""

from __future__ import annotations

import json

from app import llm
from app.audit import audited, record_usage
from app.config import settings
from app.graph.state import CaseState, review_txns
from app.guard import quote_transactions
from app.prompts import load_prompt, prompt_id
from app.rules.monitoring import load_thresholds
from app.schemas import CaseAssessment, RunConfig
from app.validate import check_assessment

PROMPT = "assess_case"


def run_config(state: CaseState) -> RunConfig:
    return state.get("run_config") or RunConfig(model=settings.model_small,
                                                prompt_version=settings.prompt_version)


def fired_typologies(state: CaseState) -> list[str]:
    fired_at = load_thresholds()["routing"]["high_risk_escalate_score"]
    return [f.typology for f in state["findings"] if f.score >= fired_at]


def build_user_message(state: CaseState, txn_block: str) -> str:
    a, p, f = state["alert"], state["profile"], state["features"]
    fired = fired_typologies(state)
    findings = "\n".join(
        f"- {x.typology}: score {x.score:.2f}{' (FIRED)' if x.typology in fired else ''}. "
        f"{x.rule_explanation} Evidence: {', '.join(x.evidence_txn_ids[:20]) or 'none'}"
        for x in state["findings"])
    guidance = "\n\n".join(f"[{c.chunk_id}] {c.typology} / {c.section}\n{c.content}"
                           for c in state.get("guidance", []))
    summary = f.model_dump(mode="json", include={
        "review_start", "review_end", "baseline_start", "txn_count", "inflow_aed",
        "outflow_aed", "cash_share", "max_single_txn_aed", "baseline_monthly_inflow_aed"})
    return (
        f"## Alert\n{a.alert_id}, rule {a.rule_id}, window {a.window_start} to {a.window_end}.\n\n"
        f"## Customer profile\n{json.dumps(p.model_dump(mode='json'), ensure_ascii=False)}\n\n"
        f"## Review window summary\n{json.dumps(summary)}\n\n"
        f"## Typology findings (fired = score 0.4 or more)\n{findings}\n\n"
        f"Fired typologies: {', '.join(fired) or 'none'}\n\n"
        f"## Guidance\n{guidance or 'none retrieved'}\n\n"
        f"## Transactions (baseline and review window)\n{txn_block}"
    )


@audited("assess_case")
def assess_case(state: CaseState) -> CaseState:
    cfg = run_config(state)
    txns = review_txns(state)
    txn_block, flagged = quote_transactions(txns, raw=not cfg.use_guard)
    messages = [{"role": "system", "content": load_prompt(PROMPT, cfg.prompt_version)},
                {"role": "user", "content": build_user_message(state, txn_block)}]
    checks = {"txn_ids": {t.txn_id for t in txns},
              "chunk_ids": {c.chunk_id for c in state.get("guidance", [])},
              "profile": state["profile"], "fired": set(fired_typologies(state))}

    assessment, errors = None, []
    for attempt in (1, 2):
        parsed, raw, usage = llm.parse(cfg.model, messages, CaseAssessment)
        record_usage(cfg.model, prompt_id(PROMPT, cfg.prompt_version),
                     usage.tokens_in, usage.tokens_out)
        if parsed is None:
            errors = ["The answer did not match the CaseAssessment schema or was refused."]
        else:
            assessment, errors = parsed, check_assessment(parsed, **checks)
        if not errors or attempt == 2:
            break
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Your answer failed these checks:\n"
                      + "\n".join(f"- {e}" for e in errors)
                      + "\nReturn the corrected assessment."}]

    if errors:  # still failing after the retry: never let it support a close
        assessment = (assessment or CaseAssessment(
            activity_summary="The assessment could not be produced.", benign_explanations=[],
            concerns=[], cited_chunk_ids=[], missing_information=[], confidence=0.0,
        )).model_copy(update={"confidence": 0.0})
    return {"assessment": assessment, "assessment_errors": errors, "flagged_txn_ids": flagged}
