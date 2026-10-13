"""build_pack: what the analyst sees at review, as plain JSON (it rides in the interrupt and
is stored in cases.pack)."""

from __future__ import annotations

from typing import Any

from app.audit import jsonable
from app.graph.state import CaseState, review_txns

MANIPULATION = "possible manipulation attempt in payment reference"


def build_pack(state: CaseState) -> dict[str, Any]:
    a, p, f = state["alert"], state["profile"], state["features"]
    by_id = {t.txn_id: t for t in review_txns(state)}
    cited = {c for c in state["assessment"].cited_chunk_ids} if "assessment" in state else set()
    return jsonable({
        "case_id": state["case_id"],
        "alert": a,
        "customer": p.model_dump(include={
            "customer_id", "full_name", "segment", "occupation", "declared_monthly_income_aed",
            "expected_activity", "risk_rating", "is_pep", "account_opened", "kyc_notes"}),
        "summary": f.model_dump(include={
            "review_start", "review_end", "baseline_start", "txn_count", "inflow_aed",
            "outflow_aed", "cash_share", "max_single_txn_aed", "baseline_monthly_inflow_aed"}),
        "findings": state["findings"],
        "assessment": state.get("assessment"),
        "assessment_errors": state.get("assessment_errors", []),
        "flagged_references": [
            {"txn_id": i, "reference": by_id[i].reference if i in by_id else None,
             "note": MANIPULATION} for i in state.get("flagged_txn_ids", [])],
        "guidance": [{"chunk_id": c.chunk_id, "typology": c.typology, "section": c.section,
                      "cited": c.chunk_id in cited} for c in state.get("guidance", [])],
        "route": state.get("route"),
    })
