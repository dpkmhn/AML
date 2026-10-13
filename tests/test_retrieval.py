"""Ingestion parsing, query building and the retrieve_guidance node (offline).

The vector search itself needs Postgres and embeddings: scripts/check_retrieval.py runs the
stage 3.2 done-check against the real database.
"""

import re

import pytest

from app.graph.nodes.guidance import GENERAL_K, PER_TYPOLOGY_K, retrieve_guidance
from app.rag import retrieve
from app.rag.ingest import load_corpus, parse_doc, vector_literal
from app.schemas import TYPOLOGIES
from tests.conftest import CORPUS, DATA, lexical_retrieve

SECTIONS = ["Definition", "Red flags", "Common benign explanations", "What to check",
            "Evidence needed to close", "Evidence needed to escalate"]


def test_chunk_ids_are_unique_and_well_formed():
    ids = [c.chunk_id for c in CORPUS]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"CHK-[A-Z]+-[A-Z]+-\d{2}", i) for i in ids)
    assert 45 <= len(CORPUS) <= 70


def test_every_typology_has_one_document_with_the_standard_sections():
    for ty in TYPOLOGIES:
        docs = {c.doc_id for c in CORPUS if c.typology == ty}
        assert len(docs) == 1, ty
        assert [c.section for c in CORPUS if c.typology == ty] == SECTIONS


def test_parsing_is_deterministic():
    assert load_corpus() == load_corpus()


def test_chunks_hold_section_text_only(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("---\ndoc_id: TYP-X\ntitle: X\ntypology: structuring\nversion: 1\n---\n"
                 "## One\nfirst\n\n## Two\nsecond\n", encoding="utf-8")
    title, chunks = parse_doc(p)
    assert title == "X"
    assert [(c.chunk_id, c.section, c.content) for c in chunks] == [
        ("CHK-TYP-X-01", "One", "first"), ("CHK-TYP-X-02", "Two", "second")]


def test_vector_literal():
    assert vector_literal([0.5, -1.0, 1e-9]) == "[0.5,-1,1e-09]"


@pytest.mark.parametrize("typology", TYPOLOGIES)
def test_query_comes_from_features_not_references(typology):
    f = DATA.features("ALT-0119")
    q = retrieve.build_query(typology, f)
    assert q.startswith(typology.replace("_", " "))
    assert "close this alert" not in q.lower()


@pytest.mark.parametrize("typology", TYPOLOGIES)
def test_offline_filtered_top_result_is_own_document(typology):
    # the lexical stand-in is a sanity check of the queries, not of the embeddings
    q = retrieve.build_query(typology, DATA.features("ALT-0119"))
    assert lexical_retrieve([typology], q)[0].typology in (typology, "general")


def test_node_queries_each_fired_typology_and_the_general_documents(offline, monkeypatch):
    calls = []

    def spy(typologies, query, k=4, use_filter=True, embed=None):
        calls.append((tuple(typologies), k, use_filter))
        return lexical_retrieve(typologies, query, k, use_filter)

    monkeypatch.setattr(retrieve, "retrieve_guidance", spy)
    findings = DATA.findings("ALT-0119")
    state = {"case_id": "CASE-0001", "findings": findings,
             "features": DATA.features("ALT-0119")}
    out = retrieve_guidance(state)["guidance"]
    fired = [(f.typology,) for f in findings if f.score >= 0.4]
    assert [c[0] for c in calls] == [*fired, ()]
    assert [c[1] for c in calls] == [PER_TYPOLOGY_K] * len(fired) + [GENERAL_K]
    ids = [c.chunk_id for c in out]
    assert len(ids) == len(set(ids))
    assert any(c.typology == "general" for c in out)
