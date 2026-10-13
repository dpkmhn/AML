"""retrieve_guidance: metadata filter first, vector similarity second.

With about 60 chunks there is no vector index: an exact scan is fast and its results are
exact. Query text is built from the features, never from payment references, so nothing a
customer wrote reaches retrieval.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text

from app import llm
from app.db import session
from app.rag.ingest import vector_literal
from app.schemas import Features, GuidanceChunk, TypologyName

_COLS = "chunk_id, doc_id, typology, section, content"
_FILTERED = text(f"""
SELECT {_COLS}, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
FROM guidance_chunks
WHERE typology = ANY(:typologies) OR typology = 'general'
ORDER BY embedding <=> CAST(:qvec AS vector)
LIMIT :k
""")
_UNFILTERED = text(f"""
SELECT {_COLS}, 1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
FROM guidance_chunks
ORDER BY embedding <=> CAST(:qvec AS vector)
LIMIT :k
""")

GENERAL_QUERY = ("level 1 alert review: routes, escalation criteria, when to close, "
                 "and how to treat customer-written payment references")


def retrieve_guidance(typologies: list[str], query: str, k: int = 4, use_filter: bool = True,
                      embed: Callable[[list[str]], list[list[float]]] | None = None,
                      ) -> list[GuidanceChunk]:
    qvec = vector_literal((embed or llm.embed)([query])[0])
    sql = _FILTERED if use_filter else _UNFILTERED
    with session("ro") as s:
        rows = s.execute(sql, {"qvec": qvec, "typologies": list(typologies), "k": k}).mappings()
        return [GuidanceChunk.model_validate(dict(r)) for r in rows]


def _aed(x: float) -> str:
    return f"AED {x:,.0f}"


def build_query(typology: TypologyName, f: Features) -> str:
    """What the analyst needs to read for this typology, phrased from the numbers."""
    facts = {
        "structuring": f"{f.cash_near_threshold_count} cash deposits just below the AED 50,000 "
                       f"reporting threshold within 14 days",
        "pass_through": f"{f.pass_through_events} large inflows sent on within 48 hours; "
                        f"inflow {_aed(f.inflow_aed)}, outflow {_aed(f.outflow_aed)}",
        "funnel": f"{f.distinct_senders} distinct senders paying in and "
                  f"{f.distinct_receivers} receivers paid out within 30 days",
        "profile_mismatch": f"30-day inflow of {_aed(f.max_inflow_30d_aed)}, "
                            f"{f.inflow_to_income_ratio:.1f} times declared monthly income",
        "dormant_reactivation": f"account inactive for {f.days_inactive_before_activity} days, "
                                f"then inflow {f.inflow_vs_prior_ratio:.1f} times the prior "
                                f"monthly average",
        "high_risk_geo": f"{f.high_risk_txn_count} transactions with high-risk countries "
                         f"{', '.join(f.high_risk_countries) or 'none'}",
    }[typology]
    return (f"{typology.replace('_', ' ')}: {facts}; red flags, what to check, and the "
            f"evidence needed to close or escalate")
