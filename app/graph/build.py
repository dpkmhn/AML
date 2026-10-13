"""The case graph: 11 nodes in a straight line, checkpointed in Postgres by case_id.

    graph = get_graph()
    graph.invoke({"case_id": "CASE-0001", "alert_id": "ALT-0042", ...},
                 {"configurable": {"thread_id": "CASE-0001"}})
"""

from __future__ import annotations

from functools import cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from app import schemas
from app.config import settings
from app.graph.nodes import assess, data, guidance, review, rules
from app.graph.state import CaseState

NODES = [
    ("load_alert", data.load_alert),
    ("get_profile", data.get_profile),
    ("get_transactions", data.get_transactions),
    ("compute_features", rules.compute_features),
    ("detect_typologies", rules.detect_typologies),
    ("retrieve_guidance", guidance.retrieve_guidance),
    ("assess_case", assess.assess_case),
    ("decide_route", review.decide_route),
    ("analyst_review", review.analyst_review),
    ("draft_narrative", review.draft_narrative),
    ("write_audit", review.write_audit),
]


def checkpoint_serde() -> JsonPlusSerializer:
    """A serializer that may rebuild every Pydantic model in app.schemas from a checkpoint.

    LangGraph only restores types it has been told about; anything else is refused (or, for
    now, restored with a warning).
    """
    models = [(schemas.__name__, name) for name, obj in vars(schemas).items()
              if isinstance(obj, type) and issubclass(obj, BaseModel)
              and obj.__module__ == schemas.__name__]
    return JsonPlusSerializer(allowed_msgpack_modules=models)


def build_graph(checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
    g = StateGraph(CaseState)
    for name, fn in NODES:
        g.add_node(name, fn)
    names = [name for name, _ in NODES]
    g.add_edge(START, names[0])
    for a, b in zip(names, names[1:], strict=False):
        g.add_edge(a, b)
    g.add_edge(names[-1], END)
    return g.compile(checkpointer=checkpointer)


@cache
def get_graph() -> CompiledStateGraph:
    """The graph with the Postgres checkpointer; creates the checkpoint tables on first use.

    Checkpoints are written through the admin connection: copilot_rw cannot create tables.
    """
    from langgraph.checkpoint.postgres import PostgresSaver

    conninfo = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    pool = ConnectionPool(conninfo, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0,
                                  "row_factory": dict_row})
    checkpointer = PostgresSaver(pool, serde=checkpoint_serde())
    checkpointer.setup()
    return build_graph(checkpointer)
