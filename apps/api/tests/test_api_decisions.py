import asyncio

import pytest
from starlette.testclient import TestClient

from trade3_api import main
from trade3_api.decision_journal import ManualDecisionJournal

_MINIMAL_BODY = {
    "symbol": "BTCUSDT",
    "action": "accept",
    "direction": "long",
    "decision_price": 100.0,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    asyncio.run(journal.initialize())
    main.app.state.manual_journal = journal

    async def _fake_benchmark_price(_request):
        return None

    monkeypatch.setattr(main, "_benchmark_price", _fake_benchmark_price)
    test_client = TestClient(main.app)
    yield test_client
    main.app.state.manual_journal = None


def test_record_and_list_decision(client):
    post_resp = client.post("/v1/decisions", json=_MINIMAL_BODY)
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert "id" in data
    assert data["symbol"] == "BTCUSDT"

    list_resp = client.get("/v1/decisions")
    assert list_resp.status_code == 200
    decisions = list_resp.json()["decisions"]
    assert any(d["id"] == data["id"] for d in decisions)


def test_stats_endpoint(client):
    client.post("/v1/decisions", json=_MINIMAL_BODY)
    resp = client.get("/v1/decisions/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total"] == 1
    assert stats["accepted"] == 1


def test_resolve_outcome(client):
    post_resp = client.post("/v1/decisions", json=_MINIMAL_BODY)
    assert post_resp.status_code == 200
    decision_id = post_resp.json()["id"]

    outcome_resp = client.post(
        f"/v1/decisions/{decision_id}/outcome", json={"price": 110.0}
    )
    assert outcome_resp.status_code == 200
    result = outcome_resp.json()
    assert result["outcome_return_pct"] == pytest.approx(0.1)


def test_resolve_unknown_returns_404(client):
    resp = client.post("/v1/decisions/999999/outcome", json={"price": 110.0})
    assert resp.status_code == 404


def test_csv_export(client):
    client.post("/v1/decisions", json=_MINIMAL_BODY)
    resp = client.get("/v1/decisions.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    first_line = resp.text.splitlines()[0]
    assert first_line.startswith("id,symbol,action")
