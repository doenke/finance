import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from finanzen.config import Settings
from finanzen.db import normalize_url
from finanzen.main import create_app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
requires_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


def reset_database(url: str) -> None:
    engine = create_engine(normalize_url(url))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    (web / "_app" / "immutable").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Finanzen</title>")
    (web / "manifest.webmanifest").write_text("{}")
    (web / "_app" / "immutable" / "app.js").write_text("console.log(1)")
    return web


def make_settings(tmp_path: Path, web_dir: Path, **overrides) -> Settings:
    base = dict(
        version="1.2.3",
        public_url="https://finanzen.example.org",
        database_url=TEST_DATABASE_URL,
        data_dir=tmp_path / "data",
        web_dir=web_dir,
        session_key="test-session-key",
        dev_login=True,
        oidc_issuer="https://id.example.org",
        oidc_client_id="finanzen",
        scheduler=False,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path: Path, web_dir: Path) -> Settings:
    return make_settings(tmp_path, web_dir)


@pytest.fixture
def client(settings: Settings):
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    reset_database(TEST_DATABASE_URL)
    app = create_app(settings)
    with TestClient(app, base_url="https://finanzen.example.org") as c:
        yield c
    app.state.engine.dispose()


def login(client: TestClient, name: str = "Anna Muster", admin: bool = True) -> None:
    res = client.get("/auth/dev", params={"name": name, "admin": admin}, follow_redirects=False)
    assert res.status_code == 302
