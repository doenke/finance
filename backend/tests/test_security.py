"""Data export without secrets, server-side sessions, locking users, audit log and the hardened MCP consent."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from finanzen.mcp.oauth import redirect_trust
from finanzen.models import Bank, BankLogin, User
from finanzen.services import audit

from .conftest import login
from .test_mcp import REDIRECT, connect, rpc, tool

ORIGIN = {"Origin": "https://finanzen.example.org"}


def second_client(client: TestClient) -> TestClient:
    return TestClient(client.app, base_url="https://finanzen.example.org")


def _uid(client: TestClient) -> int:
    return client.get("/api/me").json()["id"]


# --- 1. Data export ------------------------------------------------------------------------------


def test_export_leaves_out_secrets_and_other_peoples_bank_access(client):
    connect(client)  # creates oauth rows
    ben = second_client(client)
    login(ben, "Ben", admin=False)
    login(client, "Anna")
    anna_id, ben_id = _uid(client), _uid(ben)
    with client.app.state.sessionmaker() as db:
        bank = Bank(name="Sparkasse", blz="12345678", server_url="https://fints.example.org")
        db.add(bank)
        db.flush()
        db.add(BankLogin(bank_id=bank.id, user_id=anna_id, username="anna-login", customer_id="anna-kd", pin_encrypted="v1:secret-a", client_state="state-a", tan_medium="Handy A"))
        db.add(BankLogin(bank_id=bank.id, user_id=ben_id, username="ben-login", customer_id="ben-kd", pin_encrypted="v1:secret-b", client_state="state-b", tan_medium="Handy B"))
        db.commit()

    data = client.get("/api/export/json").json()
    assert data["scope"] == "export"
    for table in ("sessions", "oauth_clients", "oauth_codes", "oauth_tokens", "push_subscriptions"):
        assert table not in data["tables"]
    logins = {row["user_id"]: row for row in data["tables"]["bank_logins"]}
    assert all(row["pin_encrypted"] is None and row["client_state"] is None for row in logins.values())
    assert logins[anna_id]["username"] == "anna-login" and logins[anna_id]["tan_medium"] == "Handy A"
    assert logins[ben_id]["username"] == "" and logins[ben_id]["customer_id"] == "" and logins[ben_id]["tan_medium"] is None
    assert "secret-" not in str(data) and "ben-login" not in str(data)

    # The admin backup stays complete.
    from finanzen.services.backup import export_data

    with client.app.state.sessionmaker() as db:
        full = export_data(db)
    assert full["scope"] == "backup" and "oauth_tokens" in full["tables"]
    assert {r["pin_encrypted"] for r in full["tables"]["bank_logins"]} == {"v1:secret-a", "v1:secret-b"}


# --- 4. Sessions and locking ---------------------------------------------------------------------


def test_logout_invalidates_a_copied_cookie(client):
    login(client)
    stolen = client.cookies.get("finanzen_session")
    thief = second_client(client)
    thief.cookies.set("finanzen_session", stolen)
    assert thief.get("/api/me").status_code == 200
    assert client.post("/auth/logout", headers=ORIGIN).status_code == 204
    assert thief.get("/api/me").status_code == 401


def test_old_stateless_cookie_is_rejected(client):
    from finanzen.auth.session import serializer

    login(client)
    old = serializer(client.app.state.settings, "session").dumps({"uid": _uid(client)})
    other = second_client(client)
    other.cookies.set("finanzen_session", old)
    assert other.get("/api/me").status_code == 401


def test_list_and_end_own_sessions(client):
    phone = second_client(client)
    login(phone, "Anna")
    login(client, "Anna")
    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    assert client.post("/api/sessions/revoke-others", headers=ORIGIN).json() == {"ended": 1}
    assert phone.get("/api/me").status_code == 401
    assert client.get("/api/me").status_code == 200
    own = client.get("/api/sessions").json()[0]["id"]
    assert client.delete(f"/api/sessions/{own}").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_cannot_end_someone_elses_session(client):
    ben = second_client(client)
    login(ben, "Ben", admin=False)
    ben_session = ben.get("/api/sessions").json()[0]["id"]
    login(client, "Anna")
    assert client.delete(f"/api/sessions/{ben_session}").status_code == 404
    assert ben.get("/api/me").status_code == 200


def test_admin_locks_and_unlocks_a_user(client):
    viewer = second_client(client)
    login(viewer, "Viewer", admin=False)
    assert viewer.get("/api/admin/users").status_code == 403

    ben = second_client(client)
    tokens, _ = connect(ben)  # logs in as "Anna Muster"
    ben_id = _uid(ben)

    login(client, "Chefin")
    users = {u["name"]: u for u in client.get("/api/admin/users").json()}
    assert users["Anna Muster"]["sessions"] >= 1 and users["Anna Muster"]["assistants"] == 1
    assert client.put(f"/api/admin/users/{_uid(client)}/disabled", json={"disabled": True}, headers=ORIGIN).status_code == 409

    res = client.put(f"/api/admin/users/{ben_id}/disabled", json={"disabled": True}, headers=ORIGIN)
    assert res.status_code == 200 and res.json()["disabled"] is True and res.json()["sessions"] == 0
    assert ben.get("/api/me").status_code == 401
    assert ben.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 401
    refresh = ben.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": "x"})
    assert refresh.status_code in (400, 401)
    assert ben.get("/auth/dev", params={"name": "Anna Muster"}, follow_redirects=False).status_code == 403

    client.put(f"/api/admin/users/{ben_id}/disabled", json={"disabled": False}, headers=ORIGIN)
    login(ben, "Anna Muster")
    assert ben.get("/api/me").status_code == 200

    assert client.post(f"/api/admin/users/{ben_id}/logout", headers=ORIGIN).json()["sessions"] == 0
    assert ben.get("/api/me").status_code == 401
    actions = [e["action"] for e in client.get("/api/audit").json()["items"]]
    assert {"Benutzer gesperrt", "Benutzer entsperrt", "Benutzer überall abgemeldet"} <= set(actions)


# --- 5. Audit log --------------------------------------------------------------------------------


def test_audit_log_records_writes_with_user_and_object(client):
    login(client, "Anna Muster")
    acc = client.post("/api/accounts", json={"name": "Girokonto", "kind": "giro"}, headers=ORIGIN).json()
    client.post(f"/api/accounts/{acc['id']}/transactions", json={"booking_date": "2026-11-01", "amount": "-45.5", "counterparty": "REWE"}, headers=ORIGIN)
    client.post("/api/import/bookings/preview", json={"text": "a;b\n1;2", "account_id": acc["id"]}, headers=ORIGIN)
    assert client.delete(f"/api/accounts/{acc['id']}").status_code == 204
    client.post("/api/accounts", json={"name": "x"}, headers=ORIGIN)  # invalid -> not recorded

    items = client.get("/api/audit").json()["items"]
    by_action = {e["action"]: e for e in items}
    assert by_action["Konto angelegt"]["detail"].startswith("Girokonto")
    assert by_action["Konto angelegt"]["actor"] == "Anna Muster" and by_action["Konto angelegt"]["via"] == "app"
    booking = by_action["Buchung angelegt"]
    assert booking["target"] == "Konto Girokonto" and "-45,50" in booking["detail"] and "REWE" in booking["detail"]
    assert by_action["Konto gelöscht"]["target"] == "Konto Girokonto"  # name kept after deleting
    assert "Angemeldet (Entwicklung)" in by_action
    assert not any("preview" in e["action"] for e in items)
    assert len([e for e in items if e["action"] == "Konto angelegt"]) == 1
    # newest first, paging
    page = client.get("/api/audit", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["more"] is True
    rest = client.get("/api/audit", params={"before": page["items"][-1]["id"]}).json()["items"]
    assert rest[0]["id"] < page["items"][-1]["id"]


def test_audit_never_records_secrets(client):
    login(client)
    bank = client.post("/api/banks", json={"name": "Sparkasse", "blz": "12345678", "server_url": "https://fints.example.org"}, headers=ORIGIN)
    assert bank.status_code == 201
    res = client.post(f"/api/banks/{bank.json()['id']}/logins", json={"username": "geheim-user", "customer_id": "kd-4711", "pin": "98765"}, headers=ORIGIN)
    assert res.status_code == 201
    items = client.get("/api/audit").json()["items"]
    assert items[0]["action"] == "Bankzugang angelegt" and items[0]["target"] == "Bank Sparkasse"
    text = str(items)
    assert "geheim-user" not in text and "kd-4711" not in text and "98765" not in text
    assert audit.detail({"pin": "1234", "username": "u", "value": "5.00", "name": "N"}) == "N · 5,00"


def test_mcp_writes_are_recorded_with_the_assistant(client):
    tokens, _ = connect(client)
    token = tokens["access_token"]
    err, acc = tool(client, token, "create_account", {"name": "Bausparvertrag", "kind": "altersvorsorge"})
    assert not err
    tool(client, token, "add_valuation", {"account_id": acc["account_id"], "date": "2026-01-01", "value": "1234.5"})
    tool(client, token, "list_accounts")
    items = client.get("/api/audit").json()["items"]
    mcp = [e for e in items if e["via"] == "mcp"]
    assert [e["action"] for e in mcp] == ["Bewertung eingetragen", "Konto angelegt"]
    assert mcp[0]["client"] == "Claude" and mcp[0]["target"] == "Konto Bausparvertrag" and "1.234,50" in mcp[0]["detail"]
    assert any(e["action"] == "Assistent verbunden" and e["detail"] == "claude.ai" for e in items)
    assert rpc(client, token, "ping")["result"] == {}


# --- 3. MCP consent and registration --------------------------------------------------------------


def _authorize_params(client_id: str, redirect: str) -> dict:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"v" * 64).digest()).rstrip(b"=").decode()
    return {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge, "code_challenge_method": "S256", "state": "s"}


def test_redirect_trust():
    hosts = ("claude.ai", "claude.com")
    assert redirect_trust("https://claude.ai/api/mcp/auth_callback", hosts) == ("claude.ai", "known")
    assert redirect_trust("https://x.claude.com/cb", hosts) == ("x.claude.com", "known")
    assert redirect_trust("https://claude.ai.evil.example/cb", hosts) == ("claude.ai.evil.example", "unknown")
    assert redirect_trust("https://evilclaude.ai/cb", hosts)[1] == "unknown"
    assert redirect_trust("http://localhost:3334/cb", hosts) == ("localhost", "local")


def test_consent_for_unknown_host_warns_and_needs_confirmation(client):
    login(client)
    evil = "https://evil.example.com/callback"
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [evil]}).json()
    params = _authorize_params(reg["client_id"], evil)
    page = client.get("/oauth/authorize", params=params)
    assert "unbekanntes Ziel" in page.text and "evil.example.com" in page.text
    csrf = page.text.split('name="csrf" value="')[1].split('"')[0]
    res = client.post("/oauth/authorize", data={**params, "csrf": csrf, "decision": "allow"}, follow_redirects=False)
    assert res.status_code == 400 and "bestätige" in res.text
    res = client.post("/oauth/authorize", data={**params, "csrf": csrf, "decision": "allow", "confirm": "yes"}, follow_redirects=False)
    assert res.status_code == 302 and "code" in parse_qs(urlparse(res.headers["location"]).query)

    known = client.get("/oauth/authorize", params=_authorize_params(client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]}).json()["client_id"], REDIRECT))
    assert "unbekanntes Ziel" not in known.text and "claude.ai" in known.text


def test_registration_limits(client):
    assert client.post("/oauth/register", json={"redirect_uris": [f"https://a.example.com/{i}" for i in range(6)]}).status_code == 400
    assert client.post("/oauth/register", json={"redirect_uris": ["https://a.example.com/cb#frag"]}).status_code == 400
    assert client.post("/oauth/register", json={"redirect_uris": ["https://a.example.com/" + "x" * 600]}).status_code == 400
    assert client.post("/oauth/register", json=["x"]).status_code == 400
    name = client.post("/oauth/register", json={"client_name": "  A\n\nB " + "y" * 300, "redirect_uris": [REDIRECT]}).json()["client_name"]
    assert name.startswith("A B") and len(name) == 100
    for _ in range(19):
        assert client.post("/oauth/register", json={"redirect_uris": [REDIRECT]}).status_code == 201
    assert client.post("/oauth/register", json={"redirect_uris": [REDIRECT]}).status_code == 429


def test_unused_clients_are_cleaned_up(client):
    from datetime import UTC, datetime, timedelta

    from finanzen.models import OAuthClient

    old = client.post("/oauth/register", json={"redirect_uris": [REDIRECT]}).json()["client_id"]
    with client.app.state.sessionmaker() as db:
        db.get(OAuthClient, old).created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})
    with client.app.state.sessionmaker() as db:
        assert db.get(OAuthClient, old) is None


def test_user_model_has_disabled_default(client):
    login(client)
    with client.app.state.sessionmaker() as db:
        assert db.query(User).first().disabled is False
