import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from finanzen.auth import oidc
from finanzen.auth.avatar import allowed_host
from finanzen.auth.oidc import OIDCError, Provider

from .conftest import login


def test_unauthenticated_api_is_rejected(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/config").json()["provider_name"] == "Kanonenwiese SSO"


def test_dev_login_creates_user_and_person(client):
    login(client, "Anna Muster")
    me = client.get("/api/me").json()
    assert me["name"] == "Anna Muster"
    assert me["is_admin"] is True
    persons = client.get("/api/persons").json()
    assert [p["name"] for p in persons] == ["Anna"]
    assert persons[0]["id"] == me["person_id"]


def test_persons_crud_and_logout(client):
    login(client)
    res = client.post("/api/persons", json={"name": "Lena", "color": "#2563eb"}, headers={"Origin": "https://finanzen.example.org"})
    assert res.status_code == 201
    pid = res.json()["id"]
    assert client.put(f"/api/persons/{pid}", json={"name": "Lena M.", "color": "#2563eb"}).json()["name"] == "Lena M."
    own = client.get("/api/me").json()["person_id"]
    assert client.delete(f"/api/persons/{own}").status_code == 409
    assert client.delete(f"/api/persons/{pid}").status_code == 204
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_foreign_origin_is_blocked(client):
    login(client)
    res = client.post("/api/persons", json={"name": "X"}, headers={"Origin": "https://evil.example.com"})
    assert res.status_code == 403


def test_tampered_session_is_rejected(client):
    client.cookies.set("finanzen_session", "garbage")
    assert client.get("/api/me").status_code == 401


def _provider() -> Provider:
    return Provider("https://id.example.org/authorize", "https://id.example.org/token", None, "https://id.example.org/jwks", None, ["RS256"])


class FakeJWKS:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        class K:
            key = self.public_key

        return K()


def _token(private_key, **claims):
    base = {"iss": "https://id.example.org", "aud": "finanzen", "sub": "u1", "exp": int(time.time()) + 300, "nonce": "n1"}
    base.update(claims)
    return jwt.encode(base, private_key, algorithm="RS256")


def test_id_token_validation(settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = FakeJWKS(key.public_key())
    claims = oidc.validate_id_token(settings, _provider(), jwks, _token(key), "n1")
    assert claims["sub"] == "u1"
    with pytest.raises(OIDCError):
        oidc.validate_id_token(settings, _provider(), jwks, _token(key), "other")
    with pytest.raises(OIDCError):
        oidc.validate_id_token(settings, _provider(), jwks, _token(key, aud="someone-else"), "n1")
    with pytest.raises(OIDCError):
        oidc.validate_id_token(settings, _provider(), jwks, _token(key, iss="https://evil.example.com"), "n1")


def test_full_oidc_callback(client, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(oidc, "discover", lambda s: (_provider(), FakeJWKS(key.public_key())))
    res = client.get("/auth/login", params={"return_to": "/haushalt"}, follow_redirects=False)
    assert res.status_code == 302
    location = res.headers["location"]
    assert "code_challenge_method=S256" in location
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(location).query)
    state, nonce = q["state"][0], q["nonce"][0]
    token = _token(key, sub="pocket-123", nonce=nonce, name="Ben Beispiel", email="ben@example.org", groups=["family"])
    monkeypatch.setattr(oidc, "exchange_code", lambda s, p, code, verifier: {"id_token": token, "access_token": "at"})
    monkeypatch.setattr(oidc, "fetch_userinfo", lambda p, at: {})
    res = client.get("/auth/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/haushalt"
    me = client.get("/api/me").json()
    assert me["name"] == "Ben Beispiel"
    assert me["is_admin"] is False

    bad = client.get("/auth/callback", params={"code": "c", "state": "wrong"}, follow_redirects=False)
    assert bad.status_code == 400


def test_avatar_host_check():
    issuer = "https://id.example.org"
    assert allowed_host("https://id.example.org/api/users/1/profile-picture.png", issuer, ())
    assert not allowed_host("http://id.example.org/a.png", issuer, ())
    assert not allowed_host("https://169.254.169.254/latest", issuer, ())
    assert allowed_host("https://cdn.example.org/a.png", issuer, ("cdn.example.org",))
