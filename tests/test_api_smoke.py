"""Smoke tests for the FastAPI app.

These exercise the app object without hitting ClickHouse. Only the
DB-free endpoints (e.g. /healthz) are covered here so the suite stays
hermetic and fast.
"""

from fastapi.testclient import TestClient

from researchpapers.api import app


client = TestClient(app)


def test_healthz_returns_ok():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_app_metadata_is_set():
    assert app.title == "researchPapers API"
    assert app.version == "0.1.0"


def test_unknown_route_returns_404():
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404


def test_invalid_sources_query_returns_400():
    # /search requires a `q` param; an unknown `sources` value is rejected
    # before any DB call, so this stays hermetic.
    resp = client.get("/search", params={"q": "transformer", "sources": "bogus"})
    assert resp.status_code == 400
