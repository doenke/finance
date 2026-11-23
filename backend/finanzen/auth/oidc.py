"""OpenID Connect: discovery, authorization code flow with PKCE, token validation."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from ..config import Settings


class OIDCError(Exception):
    """Login failed; the message is shown to the user (German)."""


@dataclass
class Provider:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    jwks_uri: str
    end_session_endpoint: str | None
    algorithms: list[str]


_cache: dict[str, tuple[float, Provider, jwt.PyJWKClient]] = {}


def discover(settings: Settings) -> tuple[Provider, jwt.PyJWKClient]:
    cached = _cache.get(settings.oidc_issuer)
    if cached and cached[0] > time.time():
        return cached[1], cached[2]
    url = f"{settings.oidc_issuer}/.well-known/openid-configuration"
    try:
        res = httpx.get(url, timeout=8.0)
        res.raise_for_status()
        meta = res.json()
    except Exception as exc:  # noqa: BLE001
        raise OIDCError("Der Anmeldedienst ist gerade nicht erreichbar (Discovery fehlgeschlagen).") from exc
    if meta.get("issuer", "").rstrip("/") != settings.oidc_issuer:
        raise OIDCError("Die Issuer-Adresse passt nicht zur Konfiguration (OIDC_ISSUER).")
    provider = Provider(
        authorization_endpoint=meta["authorization_endpoint"],
        token_endpoint=meta["token_endpoint"],
        userinfo_endpoint=meta.get("userinfo_endpoint"),
        jwks_uri=meta["jwks_uri"],
        end_session_endpoint=meta.get("end_session_endpoint"),
        algorithms=meta.get("id_token_signing_alg_values_supported") or ["RS256"],
    )
    jwks = jwt.PyJWKClient(provider.jwks_uri, cache_keys=True)
    _cache[settings.oidc_issuer] = (time.time() + 3600, provider, jwks)
    return provider, jwks


def new_flow() -> dict[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {
        "state": secrets.token_urlsafe(24),
        "nonce": secrets.token_urlsafe(24),
        "verifier": verifier,
        "challenge": challenge,
    }


def authorization_url(settings: Settings, provider: Provider, flow: dict[str, str]) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.oidc_scopes,
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": flow["challenge"],
        "code_challenge_method": "S256",
    }
    return str(httpx.URL(provider.authorization_endpoint, params=params))


def exchange_code(settings: Settings, provider: Provider, code: str, verifier: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": verifier,
    }
    auth = (settings.oidc_client_id, settings.oidc_client_secret) if settings.oidc_client_secret else None
    try:
        res = httpx.post(provider.token_endpoint, data=data, auth=auth, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        raise OIDCError("Der Anmeldedienst ist gerade nicht erreichbar.") from exc
    if res.status_code != 200:
        error = ""
        try:
            error = res.json().get("error", "")
        except ValueError:
            pass
        if error == "invalid_client":
            raise OIDCError("Der Client ist beim Anmeldedienst unbekannt oder das Secret stimmt nicht (invalid_client).")
        if error == "invalid_grant":
            raise OIDCError(
                f"Der Anmeldecode wurde abgelehnt (invalid_grant). Stimmt die Callback-URL {settings.redirect_uri} im Client?"
            )
        raise OIDCError(f"Anmeldung fehlgeschlagen ({error or res.status_code}).")
    return res.json()


def validate_id_token(settings: Settings, provider: Provider, jwks: jwt.PyJWKClient, id_token: str, nonce: str) -> dict[str, Any]:
    try:
        key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=provider.algorithms,
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["iss", "aud", "sub", "exp"]},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise OIDCError("Das Anmeldetoken ist ungültig.") from exc
    if claims.get("nonce") != nonce:
        raise OIDCError("Das Anmeldetoken passt nicht zu dieser Anmeldung (nonce).")
    return claims


def fetch_userinfo(provider: Provider, access_token: str) -> dict[str, Any]:
    if not provider.userinfo_endpoint or not access_token:
        return {}
    try:
        res = httpx.get(provider.userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}, timeout=8.0)
        return res.json() if res.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}
