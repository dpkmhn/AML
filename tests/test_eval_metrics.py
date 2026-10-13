"""evals/metrics.py on hand-made case dicts, and the temperature fallback in app/llm.py."""

from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from app import llm
from evals import metrics


def case(alert_id, group, expected, route, *, typ=(), fired=(), gold_ev=(), cited=(),
         chunks=(), cost=0.01, lat=1.0):
    return {"alert_id": alert_id, "group": group, "expected_route": expected, "route": route,
            "golden_typologies": list(typ), "fired_typologies": list(fired),
            "golden_evidence": list(gold_ev), "cited_txn_ids": list(cited),
            "cited_chunks": [{"chunk_id": c, "typology": t} for c, t in chunks],
            "cost_usd": cost, "latency_s": lat, "error": None if route else "boom"}


CASES = [
    case("A1", "planted", "escalate", "close", typ=["funnel"], fired=["funnel"],
         gold_ev=["T1", "T2"], cited=["T1", "T9"],
         chunks=[("C1", "funnel"), ("C2", "structuring"), ("G1", "general")]),
    case("A2", "lookalike", "close", "escalate", typ=["structuring"],
         fired=["structuring", "profile_mismatch"]),
    case("A3", "trap", "escalate", "escalate", typ=["funnel"], fired=["funnel"]),
    case("A4", "trap", "escalate", "needs_info"),
    case("A5", "needs_info", "needs_info", None),
]


def test_route_metrics():
    assert metrics.missed_escalations(CASES) == ["A1"]
    assert metrics.false_escalations(CASES) == ["A2"]
    assert metrics.route_accuracy(CASES) == (1, 5)  # the failed run counts as wrong
    assert metrics.injection_failures(CASES) == (["A4"], 2)


def test_confusion_leaves_out_failed_runs():
    m = metrics.confusion(CASES)
    assert m.sum() == 4
    assert m[metrics.ROUTES.index("escalate")][metrics.ROUTES.index("close")] == 1
    assert metrics.confusion([CASES[-1]]).sum() == 0  # all failed: zeros, not an error


def test_evidence_and_citation():
    assert metrics.evidence_accuracy(CASES) == (1, 2)
    assert metrics.evidence_recall(CASES) == (1, 2)
    assert metrics.citation_accuracy(CASES) == (1, 2)  # the general chunk is left out


def test_typology_detection():
    d = metrics.typology_detection(CASES)
    assert (d["funnel"]["tp"], d["funnel"]["fp"], d["funnel"]["fn"]) == (2, 0, 0)
    assert d["profile_mismatch"]["precision"] == 0


def test_judge_agreement(tmp_path):
    p = tmp_path / "hand.csv"
    p.write_text("alert_id,customer,trigger,checks_performed,findings_with_ids,"
                 "conclusion_with_reason,faithful\nA1,1,1,1,0,1,1\nA2,,,,,,\n", "utf-8")
    hand = metrics.load_hand_scores(p)
    assert list(hand) == ["A1"]  # blank rows are not scored yet
    judged = [{"alert_id": "A1", "judge": {"customer": True, "trigger": True,
                                           "checks_performed": True, "findings_with_ids": True,
                                           "conclusion_with_reason": True, "faithful": True}}]
    r = metrics.judge_agreement(judged, hand)
    assert r["cases"] == 1 and r["same_total"] == 0 and r["item_agreement"] == pytest.approx(5 / 6)


def test_temperature_dropped_for_models_that_reject_it(monkeypatch):
    monkeypatch.setattr(llm, "_NO_TEMPERATURE", set())
    calls = []

    def method(**kw):
        calls.append(kw)
        if "temperature" in kw:
            resp = httpx.Response(400, request=httpx.Request("POST", "https://x"))
            raise BadRequestError("temperature 0 unsupported", response=resp,
                                  body={"param": "temperature"})
        return SimpleNamespace(ok=True)

    assert llm._create(method, "reasoner", messages=[]).ok
    assert llm._create(method, "reasoner", messages=[]).ok
    # tried once with temperature, then remembered: three calls, not four
    assert ["temperature" in c for c in calls] == [True, False, False]
