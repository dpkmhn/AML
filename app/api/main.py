"""The HTTP API. The analyst UI talks only to this; this talks only to the graph and the database.

    uv run uvicorn app.api.main:app --reload

POST /cases runs the graph synchronously up to the analyst review (10 to 30 s with a model),
which is fine for a demo. The case_id is the graph's thread_id, so every endpoint finds a
case's state in its checkpoint.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from pydantic import ValidationError
from sqlalchemy import text

from app import audit, cases
from app.config import settings
from app.db import session
from app.graph.build import get_graph
from app.graph.state import review_txns
from app.schemas import (
    AlertListItem,
    AnalystDecision,
    AuditRow,
    CaseCreate,
    CaseDetail,
    ReviewResult,
    RunConfig,
)
from app.tools import alerts

# The prioritised queue: what the copilot recommends escalating comes first
QUEUE_ORDER = {"escalate": 0, "needs_info": 1, "close": 2, None: 3}

app = FastAPI(title="AML Alert Triage Copilot", version="0.1.0")


def graph() -> CompiledStateGraph:
    """The checkpointed case graph; tests override this dependency."""
    return get_graph()


Graph = Annotated[CompiledStateGraph, Depends(graph)]


def _config(case_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": case_id}}


def _review_request(snapshot: StateSnapshot) -> dict[str, Any] | None:
    """The request analyst_review is paused on, or None when the case is not waiting."""
    if snapshot.next != ("analyst_review",):
        return None
    return next((i.value for t in snapshot.tasks for i in t.interrupts), None)


def _case_row(case_id: str) -> dict[str, Any]:
    row = cases.get_case(case_id)
    if row is None:
        raise HTTPException(404, f"no case {case_id}")
    return row


def _evidence_ids(pack: dict[str, Any]) -> set[str]:
    ids = {i for f in pack["findings"] if f["score"] > 0 for i in f["evidence_txn_ids"]}
    for b in (pack.get("assessment") or {}).get("benign_explanations", []):
        ids |= set(b["evidence_txn_ids"])
    return ids | {f["txn_id"] for f in pack["flagged_references"]}


def _detail(row: dict[str, Any], snapshot: StateSnapshot) -> CaseDetail:
    values = snapshot.values
    request = _review_request(snapshot)
    if row["final_route"]:
        status, pack = "decided", row["pack"]
    elif request is not None:
        status, pack = "awaiting_review", request["pack"]
    else:
        status, pack = "incomplete", None

    evidence = []
    if pack and "features" in values:
        ids = _evidence_ids(pack)
        evidence = [t for t in review_txns(values) if t.txn_id in ids]
    decision = values.get("review")
    if decision is None and pack and pack.get("review"):
        decision = AnalystDecision.model_validate(pack["review"])
    return CaseDetail(
        case_id=row["case_id"], alert_id=row["alert_id"], status=status,
        recommended_route=row["recommended_route"], pack=pack, evidence_txns=evidence,
        guidance_content={c.chunk_id: c.content for c in values.get("guidance", [])},
        decision=decision, narrative=row["narrative"],
        narrative_errors=values.get("narrative_errors", []), decided_at=row["decided_at"])


@app.get("/alerts", response_model=list[AlertListItem])
def list_alerts(status: alerts.AlertStatus | None = None) -> list[AlertListItem]:
    """The analyst queue: recommended escalations first, then oldest first."""
    routes = cases.case_routes()
    items = [AlertListItem(**a, **{k: v for k, v in routes.get(a["alert_id"], {}).items()
                                   if k != "alert_id"})
             for a in alerts.list_alerts(status)]
    return sorted(items, key=lambda a: QUEUE_ORDER[a.recommended_route])


@app.post("/cases", response_model=CaseDetail)
def create_case(body: CaseCreate, g: Graph) -> CaseDetail:
    """Open the alert's case and run it to the analyst review. A case already waiting for
    review, or already decided, is returned as it is rather than run again."""
    try:
        alerts.get_alert(body.alert_id)
    except LookupError:
        raise HTTPException(404, f"no alert {body.alert_id}") from None
    case_id = cases.start_case(body.alert_id)
    config = _config(case_id)
    row = _case_row(case_id)
    snapshot = g.get_state(config)
    if not row["final_route"] and _review_request(snapshot) is None:
        run_config = RunConfig(model=settings.model_small, prompt_version=settings.prompt_version)
        g.invoke({"case_id": case_id, "alert_id": body.alert_id, "run_config": run_config},
                 config)
        row, snapshot = _case_row(case_id), g.get_state(config)
    return _detail(row, snapshot)


@app.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, g: Graph) -> CaseDetail:
    return _detail(_case_row(case_id), g.get_state(_config(case_id)))


@app.post("/cases/{case_id}/review", response_model=ReviewResult)
def review_case(case_id: str, body: AnalystDecision, g: Graph) -> ReviewResult:
    """Resume the case with the analyst's decision. Overriding the recommendation without a
    reason is refused here with a 422, before the graph sees it."""
    _case_row(case_id)
    config = _config(case_id)
    snapshot = g.get_state(config)
    if _review_request(snapshot) is None:
        raise HTTPException(409, f"{case_id} is not waiting for review")
    recommended = snapshot.values["route"].route
    try:
        decision = AnalystDecision.model_validate(body.model_dump(),
                                                  context={"recommended": recommended})
    except ValidationError as e:
        raise RequestValidationError(
            [err | {"loc": ("body", *err["loc"])}
             for err in e.errors(include_url=False, include_context=False)]) from None

    g.invoke(Command(resume=decision.model_dump()), config)
    snapshot = g.get_state(config)
    if (request := _review_request(snapshot)) is not None:  # the graph asked again
        raise HTTPException(422, request.get("error") or "decision not accepted")
    cases.close_alert(case_id)
    v = snapshot.values
    return ReviewResult(case_id=case_id, recommended_route=recommended,
                        final_route=v["review"].final_route, reviewer=v["review"].reviewer,
                        narrative=v["narrative"],
                        narrative_errors=v.get("narrative_errors", []))


@app.get("/cases/{case_id}/audit", response_model=list[AuditRow])
def case_audit(case_id: str) -> list[AuditRow]:
    """Every step of every run of the case, in order, for replay."""
    _case_row(case_id)
    return [AuditRow(**r) for r in audit.read_trail(case_id)]


@app.get("/health")
def health() -> dict[str, Any]:
    """The database answers and the model settings are present."""
    try:
        with session("ro") as s:
            s.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(503, f"database unreachable: {type(e).__name__}") from None
    key = settings.openai_api_key
    return {"status": "ok", "model_small": settings.model_small,
            "model_strong": settings.model_strong, "prompt_version": settings.prompt_version,
            "openai_key_set": bool(key and key.get_secret_value().strip())}
