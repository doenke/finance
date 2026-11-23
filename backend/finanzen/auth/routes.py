"""Login, callback, logout and the development login."""

import html
import logging
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import User
from . import oidc
from .avatar import fetch_avatar
from .session import clear_session, serializer, set_session
from .users import upsert_user

log = logging.getLogger("finanzen.auth")
router = APIRouter(prefix="/auth")

FLOW_COOKIE = "finanzen_oidc"
FLOW_MAX_AGE = 600


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _safe_return_to(value: str | None) -> str:
    # Only relative app paths, never another origin.
    if value and value.startswith("/") and not value.startswith("//") and not value.startswith("/auth"):
        return value
    return "/"


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    body = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Anmeldung fehlgeschlagen – Finanzen</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 16px;color:#1c1f1a;background:#f6f7f4}}
@media(prefers-color-scheme:dark){{body{{color:#e8ece6;background:#121512}}}}a{{color:#15803d}}</style></head>
<body><h1>Anmeldung fehlgeschlagen</h1><p>{html.escape(message)}</p><p><a href="/">Noch einmal versuchen</a></p></body></html>"""
    return HTMLResponse(body, status_code=status)


@router.get("/login")
def login(request: Request, return_to: str | None = None) -> Response:
    settings = _settings(request)
    if not settings.oidc_enabled:
        return _error_page("Die Anmeldung über OIDC ist nicht eingerichtet (OIDC_ISSUER und OIDC_CLIENT_ID fehlen).", 503)
    try:
        provider, _ = oidc.discover(settings)
    except oidc.OIDCError as exc:
        return _error_page(str(exc), 502)
    flow = oidc.new_flow()
    response = RedirectResponse(oidc.authorization_url(settings, provider, flow), status_code=302)
    payload = {"state": flow["state"], "nonce": flow["nonce"], "verifier": flow["verifier"], "return_to": _safe_return_to(return_to)}
    response.set_cookie(
        FLOW_COOKIE,
        serializer(settings, "oidc-flow").dumps(payload),
        max_age=FLOW_MAX_AGE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/auth",
    )
    return response


@router.get("/callback")
def callback(request: Request, db: Session = Depends(get_db)) -> Response:
    settings = _settings(request)
    params = request.query_params
    if params.get("error"):
        return _error_page(f"Der Anmeldedienst meldet: {params.get('error_description') or params.get('error')}")
    token = request.cookies.get(FLOW_COOKIE)
    try:
        flow = serializer(settings, "oidc-flow").loads(token or "", max_age=FLOW_MAX_AGE)
    except BadSignature:
        return _error_page("Die Anmeldung ist abgelaufen. Bitte starte sie noch einmal.")
    if not params.get("code") or params.get("state") != flow.get("state"):
        return _error_page("Die Antwort des Anmeldedienstes passt nicht zu dieser Anmeldung (state).")
    try:
        provider, jwks = oidc.discover(settings)
        tokens = oidc.exchange_code(settings, provider, params["code"], flow["verifier"])
        claims = oidc.validate_id_token(settings, provider, jwks, tokens.get("id_token", ""), flow["nonce"])
    except oidc.OIDCError as exc:
        return _error_page(str(exc))
    access_token = tokens.get("access_token", "")
    userinfo = oidc.fetch_userinfo(provider, access_token)
    if userinfo.get("sub") and userinfo["sub"] != claims["sub"]:
        return _error_page("Die Benutzerdaten passen nicht zum Anmeldetoken.")
    merged = {**userinfo, **{k: v for k, v in claims.items() if v not in (None, "", [])}}
    if "groups" in userinfo and "groups" not in claims:
        merged["groups"] = userinfo["groups"]

    user = upsert_user(db, merged, settings.oidc_admin_group)
    picture = merged.get("picture")
    if isinstance(picture, str) and picture:
        result = fetch_avatar(picture, access_token, settings.oidc_issuer, settings.avatar_hosts)
        if result:
            user.avatar, user.avatar_hash = result
    db.commit()

    response = RedirectResponse(flow.get("return_to") or "/", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path="/auth")
    set_session(response, settings, user.id)
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    response = Response(status_code=204)
    clear_session(response, _settings(request))
    return response


@router.get("/dev")
def dev_login(request: Request, name: str = "Entwickler", admin: bool = True, db: Session = Depends(get_db)) -> Response:
    """Login without an identity provider. Only active with DEV_LOGIN=true – never in production."""
    settings = _settings(request)
    if not settings.dev_login:
        return Response(status_code=404)
    slug = re.sub(r"[^\w]+", "-", name.lower()).strip("-") or "dev"
    claims = {"sub": f"dev:{slug}", "name": name, "email": f"{slug}@example.org", "groups": [settings.oidc_admin_group] if admin else []}
    user: User = upsert_user(db, claims, settings.oidc_admin_group)
    db.commit()
    response = RedirectResponse("/", status_code=302)
    set_session(response, settings, user.id)
    return response
