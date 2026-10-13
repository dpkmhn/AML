"""The API offline: the graph runs on an in-memory checkpointer, the case rows live in a dict,
and the model is the FakeLLM from conftest.py."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app import audit, cases
from app.api import main
from app.graph.build import build_graph, checkpoint_serde
from app.tools import alerts
from tests.conftest import NARRATIVE


class FakeCases:
    """The cases table as a dict, with the functions of app/cases.py that the API calls."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.closed: list[str] = []

    def start_case(self, alert_id: str) -> str:
        for row in self.rows.values():
            if row["alert_id"] == alert_id:
                return row["case_id"]
        case_id = f"CASE-{len(self.rows) + 1:04d}"
        self.rows[case_id] = {"case_id": case_id, "alert_id": alert_id, "kind": "case",
                              "recommended_route": None, "final_route": None, "reviewer": None,
                              "override_reason": None, "pack": None, "narrative": None,
                              "decided_at": None}
        return case_id

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return self.rows.get(case_id)

    def set_recommended_route(self, case_id: str, route: str) -> None:
        self.rows[case_id]["recommended_route"] = route

    def save_decision(self, case_id: str, **kw: Any) -> None:
        self.rows[case_id].update(kw, decided_at=datetime.now(UTC))

    def close_alert(self, case_id: str) -> None:
        self.closed.append(case_id)

    def case_routes(self) -> dict[str, dict[str, Any]]:
        return {r["alert_id"]: {k: r[k] for k in ("alert_id", "case_id", "recommended_route",
                                                  "final_route")}
                for r in self.rows.values()}


@pytest.fixture
def api(offline, monkeypatch):
    store = FakeCases()
    for name in ("start_case", "get_case", "set_recommended_route", "save_decision",
                 "close_alert", "case_routes"):
        monkeypatch.setattr(cases, name, getattr(store, name))
    monkeypatch.setattr(audit, "read_trail", lambda c: [
        {"id": n, **r, "output": json.loads(r["output"]), "created_at": datetime.now(UTC)}
        for n, r in enumerate(offline.audit_rows, 1) if r["case_id"] == c])
    g = build_graph(InMemorySaver(serde=checkpoint_serde()))
    main.app.dependency_overrides[main.graph] = lambda: g
    yield TestClient(main.app), store
    main.app.dependency_overrides.clear()


def other_route(route: str) -> str:
    return "escalate" if route != "escalate" else "close"


def test_case_runs_to_review_and_has_its_pack(api):
    client, _ = api
    r = client.post("/cases", json={"alert_id": "ALT-0042"})
    assert r.status_code == 200
    case = r.json()
    assert case["case_id"] == "CASE-0001"
    assert case["status"] == "awaiting_review"
    assert case["pack"]["route"]["route"] == case["recommended_route"]
    assert case["pack"]["alert"]["alert_id"] == "ALT-0042"
    # every evidence transaction the pack names is served with it
    served = {t["txn_id"] for t in case["evidence_txns"]}
    named = {i for f in case["pack"]["findings"] if f["score"] > 0 for i in f["evidence_txn_ids"]}
    assert named <= served
    assert set(case["guidance_content"]) == {c["chunk_id"] for c in case["pack"]["guidance"]}

    # opening it again returns the paused case without running the graph a second time
    again = client.post("/cases", json={"alert_id": "ALT-0042"}).json()
    assert again["case_id"] == "CASE-0001"
    assert again["pack"] == case["pack"]


def test_unknown_alert_is_404(api):
    client, _ = api
    assert client.post("/cases", json={"alert_id": "ALT-9999"}).status_code == 404
    assert client.get("/cases/CASE-9999").status_code == 404


def test_override_without_a_reason_is_422(api):
    client, store = api
    case = client.post("/cases", json={"alert_id": "ALT-0042"}).json()
    override = other_route(case["recommended_route"])
    for reason in (None, "   "):
        r = client.post(f"/cases/{case['case_id']}/review",
                        json={"reviewer": "deepak", "final_route": override,
                              "override_reason": reason})
        assert r.status_code == 422
        assert "override_reason is required" in r.text
    # nothing was decided: the case still waits, the alert is still open
    assert client.get(f"/cases/{case['case_id']}").json()["status"] == "awaiting_review"
    assert store.closed == []


def test_override_with_a_reason_decides_and_writes_the_narrative(api):
    client, store = api
    case = client.post("/cases", json={"alert_id": "ALT-0042"}).json()
    override = other_route(case["recommended_route"])
    r = client.post(f"/cases/{case['case_id']}/review",
                    json={"reviewer": "deepak", "final_route": override,
                          "override_reason": "source of funds seen in the branch file"})
    assert r.status_code == 200
    result = r.json()
    assert result["final_route"] == override
    assert result["recommended_route"] == case["recommended_route"]
    assert NARRATIVE.splitlines()[0] in result["narrative"]
    assert store.closed == ["CASE-0001"]

    detail = client.get("/cases/CASE-0001").json()
    assert detail["status"] == "decided"
    assert detail["decision"]["override_reason"] == "source of funds seen in the branch file"
    assert detail["narrative"] == result["narrative"]
    # a decided case cannot be reviewed again
    again = client.post("/cases/CASE-0001/review",
                        json={"reviewer": "deepak", "final_route": override,
                              "override_reason": "again"})
    assert again.status_code == 409

    steps = [row["step"] for row in client.get("/cases/CASE-0001/audit").json()]
    assert steps[0] == "load_alert"
    assert steps[-1] == "write_audit"


def test_accepting_the_recommendation_needs_no_reason(api):
    client, _ = api
    case = client.post("/cases", json={"alert_id": "ALT-0042"}).json()
    r = client.post(f"/cases/{case['case_id']}/review",
                    json={"reviewer": "deepak", "final_route": case["recommended_route"]})
    assert r.status_code == 200


def test_queue_puts_recommended_escalations_first(api, monkeypatch):
    client, store = api

    def alert(alert_id: str) -> dict[str, Any]:
        return {"alert_id": alert_id, "customer_id": "CUS-0001", "customer_name": "A Customer",
                "rule_id": "TM-STR-01", "window_start": date(2026, 1, 1),
                "window_end": date(2026, 1, 31), "created_at": datetime(2026, 2, 1, tzinfo=UTC),
                "status": "open"}

    monkeypatch.setattr(alerts, "list_alerts", lambda status: [alert(f"ALT-000{i}")
                                                               for i in range(1, 5)])
    for alert_id, route in [("ALT-0001", "close"), ("ALT-0002", "needs_info"),
                            ("ALT-0003", "escalate")]:
        store.set_recommended_route(store.start_case(alert_id), route)
    queue = client.get("/alerts", params={"status": "open"}).json()
    assert [a["alert_id"] for a in queue] == ["ALT-0003", "ALT-0002", "ALT-0001", "ALT-0004"]
    assert queue[0]["case_id"] == "CASE-0003"
    assert client.get("/alerts", params={"status": "bogus"}).status_code == 422
