"""retrieve_guidance: one query per fired typology, plus the general procedure chunks."""

from __future__ import annotations

from app.audit import audited
from app.graph.state import CaseState
from app.rag import retrieve
from app.rules.monitoring import load_thresholds

PER_TYPOLOGY_K = 4
GENERAL_K = 3


@audited("retrieve_guidance")
def retrieve_guidance(state: CaseState) -> CaseState:
    fired_at = load_thresholds()["routing"]["high_risk_escalate_score"]
    use_filter = state["run_config"].use_filter if "run_config" in state else True
    chunks = []
    for f in state["findings"]:
        if f.score >= fired_at:
            q = retrieve.build_query(f.typology, state["features"])
            chunks += retrieve.retrieve_guidance([f.typology], q, k=PER_TYPOLOGY_K,
                                                 use_filter=use_filter)
    # the general documents only: an empty typology list leaves the 'general' clause
    chunks += retrieve.retrieve_guidance([], retrieve.GENERAL_QUERY, k=GENERAL_K)
    seen: set[str] = set()
    unique = [c for c in chunks if not (c.chunk_id in seen or seen.add(c.chunk_id))]
    return {"guidance": unique}
