import os

import pytest
from fastapi.testclient import TestClient


def make_client(monkeypatch, tmp_path, database_url: str) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    import importlib

    import finanzen.main

    importlib.reload(finanzen.main)
    return TestClient(finanzen.main.app)


def test_healthz_reports_unreachable_db(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, "postgresql://nobody@127.0.0.1:1/none")
    res = client.get("/healthz")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "error"
    assert body["version"] == "1.2.3"
    assert body["checks"] == {"db": "error", "data": "ok"}
    assert res.headers["cache-control"] == "no-store"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_healthz_ok_with_db(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, os.environ["TEST_DATABASE_URL"])
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["checks"] == {"db": "ok", "data": "ok"}


def test_liveness_and_placeholder(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, "")
    assert client.get("/healthz/live").json() == {"status": "ok", "version": "1.2.3"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Finanzen" in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
