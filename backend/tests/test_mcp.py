import base64
import hashlib
import json
from decimal import Decimal as D
from urllib.parse import parse_qs, urlparse

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def connect(client):
    """Full OAuth dance: discovery, registration, consent, code exchange. Returns the access token."""
    res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert res.status_code == 401
    assert "resource_metadata" in res.headers["www-authenticate"]
    meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"].endswith("/mcp")
    as_meta = client.get("/.well-known/oauth-authorization-server").json()
    assert as_meta["code_challenge_methods_supported"] == ["S256"]
    reg = client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]})
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz"}
    # Not logged in yet -> app login
    client.cookies.clear()
    res = client.get("/oauth/authorize", params=params, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"].startswith("/auth/login?")
    login(client, "Anna Muster")
    page = client.get("/oauth/authorize", params=params)
    assert "Claude mit Finanzen verbinden" in page.text
    csrf = page.text.split('name="csrf" value="')[1].split('"')[0]
    res = client.post("/oauth/authorize", data={**params, "csrf": csrf, "decision": "allow"}, headers=ORIGIN, follow_redirects=False)
    assert res.status_code == 302
    q = parse_qs(urlparse(res.headers["location"]).query)
    assert q["state"] == ["xyz"]
    code = q["code"][0]
    bad = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id, "redirect_uri": REDIRECT, "code_verifier": "wrong"})
    assert bad.status_code == 400  # and the code is now burnt
    # second round for a valid exchange
    page = client.get("/oauth/authorize", params=params)
    csrf = page.text.split('name="csrf" value="')[1].split('"')[0]
    res = client.post("/oauth/authorize", data={**params, "csrf": csrf, "decision": "allow"}, headers=ORIGIN, follow_redirects=False)
    code = parse_qs(urlparse(res.headers["location"]).query)["code"][0]
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id, "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    tokens = tok.json()
    assert client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "client_id": client_id, "redirect_uri": REDIRECT, "code_verifier": verifier}).status_code == 400
    return tokens, client_id


def rpc(client, token, method, params=None, mid=1):
    res = client.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    return res.json()


def tool(client, token, name, args=None):
    out = rpc(client, token, "tools/call", {"name": name, "arguments": args or {}})["result"]
    return out["isError"], json.loads(out["content"][0]["text"]) if not out["isError"] else out["content"][0]["text"]


def test_mcp_oauth_and_tools(client):
    tokens, client_id = connect(client)
    access = tokens["access_token"]
    init = rpc(client, access, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={"Authorization": f"Bearer {access}"}).status_code == 202
    names = {t["name"] for t in rpc(client, access, "tools/list")["result"]["tools"]}
    assert {"list_accounts", "create_account", "add_valuation", "add_transaction", "add_trade"} <= names
    assert not any("delete" in n for n in names)

    err, acc = tool(client, access, "create_account", {"name": "HDI Basisrente", "kind": "altersvorsorge", "institution": "HDI", "opened_on": "2011-10-01", "details": {"product": "ruerup", "expected_pension": "168.76"}, "owners": [{"person": "Anna", "share": 1}]})
    assert not err, acc
    aid = acc["account_id"]
    for d, v in [("2023-12-31", "9205.57"), ("2024-12-31", "10374.24"), ("2025-12-31", "11600.38")]:
        assert not tool(client, access, "add_valuation", {"account_id": aid, "date": d, "value": v})[0]
    assert not tool(client, access, "add_transaction", {"account_id": aid, "date": "2025-06-30", "amount": "1065.75", "kind": "contribution"})[0]
    err, detail = tool(client, access, "get_account", {"account_id": aid})
    assert D(detail["value"]) == D("11600.38")
    assert len(detail["valuations"]) == 3
    err, accounts = tool(client, access, "list_accounts")
    assert accounts[0]["owners"][0]["person"] == "Anna"
    # the app (session) sees the new account
    assert any(a["name"] == "HDI Basisrente" for a in client.get("/api/accounts").json())
    err, msg = tool(client, access, "add_valuation", {"account_id": 99999, "date": "2025-01-01", "value": 1})
    assert err and "nicht gefunden" in msg
    err, msg = tool(client, access, "create_account", {"name": "X", "kind": "unknown"})
    assert err
    err, nw = tool(client, access, "get_net_worth")
    assert D(nw["current"]["net"]) == D("11600.38")
    unknown = rpc(client, access, "tools/call", {"name": "delete_everything"})
    assert unknown["error"]["code"] == -32602

    # refresh rotation
    new = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}).json()
    assert new["access_token"] != access
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}).status_code == 400

    # settings: list and disconnect
    clients = client.get("/api/mcp/clients").json()
    assert clients["url"].endswith("/mcp") and clients["clients"][0]["name"] == "Claude"
    assert client.delete(f"/api/mcp/clients/{client_id}", headers=ORIGIN).status_code == 204
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 401


def test_registration_and_consent_validation(client):
    assert client.post("/oauth/register", json={"redirect_uris": ["http://evil.example.com/cb"]}).status_code == 400
    login(client)
    reg = client.post("/oauth/register", json={"client_name": "X", "redirect_uris": [REDIRECT]}).json()
    page = client.get("/oauth/authorize", params={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": "https://other.example.com/cb", "code_challenge": "a", "code_challenge_method": "S256"})
    assert "Rücksprungadresse" in page.text
    page = client.get("/oauth/authorize", params={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "code_challenge": "a", "code_challenge_method": "plain"})
    assert "PKCE" in page.text
    # forged consent without CSRF token
    res = client.post("/oauth/authorize", data={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "code_challenge": "a", "code_challenge_method": "S256", "decision": "allow", "csrf": "x"}, follow_redirects=False)
    assert res.status_code != 302
    deny = client.get("/oauth/authorize", params={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "code_challenge": "a", "code_challenge_method": "S256", "state": "s"})
    csrf = deny.text.split('name="csrf" value="')[1].split('"')[0]
    res = client.post("/oauth/authorize", data={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT, "code_challenge": "a", "code_challenge_method": "S256", "state": "s", "decision": "deny", "csrf": csrf}, follow_redirects=False)
    assert "error=access_denied" in res.headers["location"]
