from fastapi.testclient import TestClient

from finanzen.main import create_app

from .conftest import make_settings, requires_db


def test_healthz_unreachable_db(tmp_path, web_dir, monkeypatch):
    settings = make_settings(tmp_path, web_dir, database_url="postgresql://nobody@127.0.0.1:1/none")
    app = create_app(settings, migrate=False)
    res = TestClient(app).get("/healthz")
    assert res.status_code == 503
    body = res.json()
    assert body == {"status": "error", "version": "1.2.3", "checks": {"db": "error", "data": "ok"}}
    assert res.headers["cache-control"] == "no-store"


def test_liveness_and_spa(tmp_path, web_dir):
    app = create_app(make_settings(tmp_path, web_dir, database_url=""))
    client = TestClient(app)
    assert client.get("/healthz/live").json() == {"status": "ok", "version": "1.2.3"}
    page = client.get("/konten/42")
    assert page.status_code == 200
    assert "Finanzen" in page.text
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get("/_app/immutable/app.js").headers["cache-control"].endswith("immutable")
    assert client.get("/missing.png").status_code == 404
    assert client.get("/api/unknown").status_code == 404


@requires_db
def test_healthz_ok(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["checks"] == {"db": "ok", "data": "ok"}


def test_share_target_fallback(tmp_path, web_dir):
    app = create_app(make_settings(tmp_path, web_dir, database_url=""))
    res = TestClient(app).post("/import/teilen", data={"x": "1"}, follow_redirects=False)
    assert res.status_code == 303 and res.headers["location"] == "/import?geteilt=fehler"
