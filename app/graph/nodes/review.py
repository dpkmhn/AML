"""decide_route, analyst_review, draft_narrative, write_audit: the case's last four steps.

The rules recommend, the analyst decides, and the narrative is written from the analyst's
decision rather than from the recommendation. Nothing here can set a final route without an
AnalystDecision.
"""

from __future__ import annotations

import json
import re

from langgraph.types import interrupt
from pydantic import ValidationError

from app import cases, llm
from app.audit import audited, jsonable, record_usage
from app.graph.nodes.assess import fired_typologies, run_config
from app.graph.pack import build_pack
from app.graph.state import CaseState, review_txns
from app.guard import quote_transactions
from app.prompts import load_prompt, prompt_id
from app.rules import routing
from app.rules.monitoring import load_thresholds
from app.schemas import AnalystDecision
from app.validate import CHUNK_ID, TXN_ID

NARRATIVE_PROMPT = "draft_narrative"
INTERNAL = "Internal: do not disclose to the customer"
HEADINGS = ["Customer", "Trigger", "Checks performed", "Findings", "Conclusion and reason"]
MAX_EVIDENCE_TXNS = 60


@audited("decide_route")
def decide_route(state: CaseState) -> CaseState:
    p = state["profile"]
    route = routing.decide_route(
        state["findings"], state["assessment"], risk_rating=p.risk_rating,
        kyc_notes=p.kyc_notes, known_txn_ids={t.txn_id for t in review_txns(state)},
        t=load_thresholds())
    cases.set_recommended_route(state["case_id"], route.route)
    return {"route": route}


@audited("analyst_review")
def analyst_review(state: CaseState) -> CaseState:
    """Pause for the analyst. An invalid answer (an override with no reason) asks again."""
    recommended = state["route"].route
    request = {"case_id": state["case_id"], "recommended_route": recommended,
               "pack": build_pack(state)}
    while True:
        answer = interrupt(request)
        try:
            decision = AnalystDecision.model_validate(answer,
                                                      context={"recommended": recommended})
        except ValidationError as e:
            request = {**request, "error": "; ".join(err["msg"] for err in e.errors())}
            continue
        return {"review": decision}


def _evidence_ids(state: CaseState) -> set[str]:
    fired = set(fired_typologies(state))
    ids = {i for f in state["findings"] if f.typology in fired for i in f.evidence_txn_ids}
    a = state["assessment"]
    ids |= {i for b in a.benign_explanations for i in b.evidence_txn_ids}
    for text in [a.activity_summary, *a.concerns]:
        ids |= set(TXN_ID.findall(text))
    return ids | set(state.get("flagged_txn_ids", []))


def narrative_message(state: CaseState) -> str:
    ids = _evidence_ids(state)
    evidence = [t for t in review_txns(state) if t.txn_id in ids][:MAX_EVIDENCE_TXNS]
    block, _ = quote_transactions(evidence)
    pack = build_pack(state)
    facts = {k: pack[k] for k in ("alert", "customer", "summary", "assessment",
                                  "flagged_references", "guidance")}
    facts["findings"] = [f for f in pack["findings"] if f["score"] > 0]
    facts["recommended_route"] = jsonable(state["route"])
    facts["analyst_decision"] = jsonable(state["review"])
    return (f"## Case facts\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n\n"
            f"## Evidence transactions\n{block}")


def check_narrative(text: str, *, txn_ids: set[str], chunk_ids: set[str]) -> list[str]:
    errors = []
    if bad := sorted(set(TXN_ID.findall(text)) - txn_ids):
        errors.append(f"Transaction IDs not in the case: {', '.join(bad)}.")
    if bad := sorted(set(CHUNK_ID.findall(text)) - chunk_ids):
        errors.append(f"Chunk IDs not in the case: {', '.join(bad)}.")
    lines = {line.strip().strip("#*: ").casefold() for line in text.splitlines()}
    if missing := [h for h in HEADINGS if h.casefold() not in lines]:
        errors.append(f"Missing headings (each on its own line): {', '.join(missing)}.")
    return errors


@audited("draft_narrative")
def draft_narrative(state: CaseState) -> CaseState:
    cfg = run_config(state)
    messages = [{"role": "system", "content": load_prompt(NARRATIVE_PROMPT, cfg.prompt_version)},
                {"role": "user", "content": narrative_message(state)}]
    known = {"txn_ids": {t.txn_id for t in review_txns(state)},
             "chunk_ids": {c.chunk_id for c in state.get("guidance", [])}}
    for attempt in (1, 2):
        text, usage = llm.complete(cfg.model, messages)
        record_usage(cfg.model, prompt_id(NARRATIVE_PROMPT, cfg.prompt_version),
                     usage.tokens_in, usage.tokens_out)
        errors = check_narrative(text, **known)
        if not errors or attempt == 2:
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "The narrative failed these checks:\n"
                      + "\n".join(f"- {e}" for e in errors) + "\nRewrite it."}]
    body = re.sub(rf"^\s*{re.escape(INTERNAL)}\.?\s*", "", text.strip())
    return {"narrative": f"{INTERNAL}.\n\n{body}", "narrative_errors": errors}


@audited("write_audit")
def write_audit(state: CaseState) -> CaseState:
    review = state["review"]
    cases.save_decision(
        state["case_id"], recommended_route=state["route"].route,
        final_route=review.final_route, reviewer=review.reviewer,
        override_reason=review.override_reason,
        pack=build_pack(state) | {"review": jsonable(review),
                                  "narrative_errors": state.get("narrative_errors", [])},
        narrative=state["narrative"])
    return {}
