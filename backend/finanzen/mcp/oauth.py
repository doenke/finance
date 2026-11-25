"""Minimal OAuth 2.1 authorization server for the MCP endpoint.

- Discovery: /.well-known/oauth-protected-resource and /.well-known/oauth-authorization-server
- Dynamic client registration (public clients, PKCE S256 required)
- The user logs in with the normal app session (Pocket ID) and confirms on a consent page
- Opaque access tokens (1 h) and rotating refresh tokens (60 days); only hashes are stored
"""

import base64
import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature
from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from ..auth.session import serializer, session_user
from ..db import get_db
from ..models import OAuthClient, OAuthCode, OAuthToken, User
from ..services import audit

router = APIRouter()

ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=60)
CODE_TTL = timedelta(minutes=5)
MAX_REDIRECT_URIS = 5
MAX_URI_LENGTH = 500
UNUSED_CLIENT_TTL = timedelta(days=1)
MAX_REGISTRATIONS_PER_HOUR = 20
NO_STORE = {"Cache-Control": "no-store"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _base(request: Request) -> str:
    return request.app.state.settings.public_url.rstrip("/")


def _now() -> datetime:
    return datetime.now(UTC)


def _valid_redirect(uri: str) -> bool:
    if len(uri) > MAX_URI_LENGTH or any(c.isspace() for c in uri):
        return False
    parsed = urlparse(uri)
    if parsed.fragment or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")


def redirect_trust(uri: str, trusted_hosts: tuple[str, ...]) -> tuple[str, str]:
    """(host, trust) for a redirect URI; trust is 'known' (configured assistant), 'local' (this device) or 'unknown'."""
    host = (urlparse(uri).hostname or "").lower()
    if host in ("localhost", "127.0.0.1"):
        return host, "local"
    if any(host == h or host.endswith("." + h) for h in trusted_hosts):
        return host, "known"
    return host, "unknown"


# --- Discovery ------------------------------------------------------------------------------------


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse({"resource": f"{base}/mcp", "authorization_servers": [base], "bearer_methods_supported": ["header"], "resource_name": "Finanzen"})


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": ["finanzen"],
        }
    )


# --- Registration ---------------------------------------------------------------------------------


@router.post("/oauth/register")
async def register(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS or not all(isinstance(u, str) and _valid_redirect(u) for u in uris):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
    # Registration is open (DCR), so clean up clients that never got connected and cap the rate.
    unused = ~exists().where(OAuthToken.client_id == OAuthClient.id) & ~exists().where(OAuthCode.client_id == OAuthClient.id)
    db.execute(delete(OAuthClient).where(OAuthClient.created_at < _now() - UNUSED_CLIENT_TTL, unused).execution_options(synchronize_session=False))
    recent = db.scalar(select(func.count()).select_from(OAuthClient).where(OAuthClient.created_at > _now() - timedelta(hours=1))) or 0
    if recent >= MAX_REGISTRATIONS_PER_HOUR:
        db.commit()
        return JSONResponse({"error": "temporarily_unavailable", "error_description": "Zu viele Registrierungen, bitte später erneut versuchen."}, status_code=429, headers={"Retry-After": "3600"})
    name = " ".join(str(body.get("client_name") or "MCP-Client").split())[:100] or "MCP-Client"
    client = OAuthClient(id=secrets.token_urlsafe(24), name=name, redirect_uris=uris)
    db.add(client)
    db.commit()
    return JSONResponse(
        {
            "client_id": client.id,
            "client_name": client.name,
            "redirect_uris": uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "client_id_issued_at": int(_now().timestamp()),
        },
        status_code=201,
        headers=NO_STORE,
    )


# --- Authorization (login + consent) --------------------------------------------------------------


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{html.escape(title)} – Finanzen</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:#f4f5f1;color:#1c1f1a}}
.card{{background:#fff;border:1px solid #dde1d8;border-radius:14px;padding:28px 24px;max-width:26rem;width:100%}}
h1{{font-size:1.3rem;margin:0 0 8px}} p{{color:#5d6459}} ul{{padding-left:20px;color:#1c1f1a}}
.row{{display:flex;gap:12px;margin-top:20px}} .warn{{border:1px solid #d97706;background:#fffbeb;color:#78350f;border-radius:10px;padding:10px 12px;margin:12px 0}}
.warn p{{color:inherit;margin:4px 0}} label{{display:flex;gap:8px;align-items:flex-start;margin-top:8px}} .host{{font-family:ui-monospace,monospace;overflow-wrap:anywhere}} button{{font:inherit;font-weight:500;min-height:42px;padding:0 18px;border-radius:10px;border:1px solid #dde1d8;background:#fff;cursor:pointer}}
button.primary{{background:#15803d;border-color:#15803d;color:#fff}}
@media(prefers-color-scheme:dark){{body{{background:#101310;color:#e8ece6}}.card{{background:#181d18;border-color:#2d342c}}p{{color:#9aa396}}ul{{color:#e8ece6}}button{{background:#181d18;color:#e8ece6;border-color:#2d342c}}button.primary{{background:#4ade80;border-color:#4ade80;color:#0b1a10}}.warn{{background:#2a1f0a;color:#fde68a;border-color:#b45309}}}}
</style></head><body><div class="card">{body}</div></body></html>""",
        status_code=status,
        headers=NO_STORE,
    )


def _error(message: str, status: int = 400) -> HTMLResponse:
    return _page("Fehler", f"<h1>Verbindung nicht möglich</h1><p>{html.escape(message)}</p>", status)


def _check_request(db: Session, params: dict[str, str]) -> OAuthClient | HTMLResponse:
    client = db.get(OAuthClient, params.get("client_id", ""))
    if client is None:
        return _error("Unbekannter Client. Bitte die Verbindung im Assistenten neu einrichten.")
    if params.get("redirect_uri") not in client.redirect_uris:
        return _error("Die Rücksprungadresse passt nicht zum registrierten Client.")
    if params.get("response_type") != "code":
        return _error("Nicht unterstützter response_type.")
    if params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
        return _error("PKCE (S256) ist erforderlich.")
    return client


def _redirect_with(uri: str, values: dict[str, str]) -> RedirectResponse:
    sep = "&" if "?" in uri else "?"
    return RedirectResponse(f"{uri}{sep}{urlencode(values)}", status_code=302)


@router.get("/oauth/authorize")
def authorize(request: Request, db: Session = Depends(get_db)) -> Response:
    params = dict(request.query_params)
    checked = _check_request(db, params)
    if isinstance(checked, HTMLResponse):
        return checked
    user = session_user(request, db)
    if user is None:
        # Log in with the normal app login and come back here.
        return_to = request.url.path + "?" + request.url.query
        return RedirectResponse("/auth/login?" + urlencode({"return_to": return_to}), status_code=302)
    csrf = serializer(request.app.state.settings, "oauth-consent").dumps({"uid": user.id, "client": checked.id})
    hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in params.items() if k not in ("csrf", "decision", "confirm"))
    host, trust = redirect_trust(params["redirect_uri"], request.app.state.settings.mcp_trusted_hosts)
    if trust == "unknown":
        where = f"""<div class="warn"><p><strong>Achtung: unbekanntes Ziel.</strong> Der Zugriff geht an <span class="host">{html.escape(host)}</span>.
Diese Adresse gehört zu keinem bekannten Assistenten. Den Namen „{html.escape(checked.name)}“ hat der Client selbst angegeben.</p>
<p>Erlaube nur, wenn du diese Verbindung gerade selbst eingerichtet hast – sonst versucht vielleicht jemand, an eure Finanzdaten zu kommen.</p>
<label><input type="checkbox" name="confirm" value="yes"> Ja, ich habe die Verbindung zu {html.escape(host)} gerade selbst gestartet.</label></div>"""
    elif trust == "local":
        where = '<p>Der Zugriff geht an ein Programm <strong>auf diesem Gerät</strong> (localhost).</p>'
    else:
        where = f'<p>Der Zugriff geht an <strong class="host">{html.escape(host)}</strong>.</p>'
    body = f"""<h1>{html.escape(checked.name)} mit Finanzen verbinden?</h1>
{where}
<p>Angemeldet als <strong>{html.escape(user.name)}</strong>. Der Assistent darf dann in eurem Haushalt:</p>
<ul><li>Konten, Depots, Anlagen und Auswertungen lesen</li><li>Konten anlegen sowie Bewertungen, Buchungen, Kontostände und Depot-Transaktionen eintragen</li></ul>
<p>Löschen kann er nichts. Du kannst die Verbindung jederzeit in den Einstellungen trennen.</p>
<form method="post" action="/oauth/authorize">{hidden}<input type="hidden" name="csrf" value="{html.escape(csrf)}">
<div class="row"><button class="primary" name="decision" value="allow">Erlauben</button><button name="decision" value="deny">Ablehnen</button></div></form>"""
    return _page("Zugriff erlauben", body)


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode()
    return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}


@router.post("/oauth/authorize")
async def authorize_decision(request: Request, db: Session = Depends(get_db)) -> Response:
    params = await _form(request)
    checked = _check_request(db, params)
    if isinstance(checked, HTMLResponse):
        return checked
    user = session_user(request, db)
    uid = user.id if user else None
    try:
        data = serializer(request.app.state.settings, "oauth-consent").loads(params.get("csrf", ""), max_age=900)
    except BadSignature:
        return _error("Die Anfrage ist abgelaufen. Bitte die Verbindung im Assistenten neu starten.")
    if uid is None or data.get("uid") != uid or data.get("client") != checked.id:
        return _error("Die Anfrage passt nicht zur Anmeldung.", 403)
    state = {"state": params["state"]} if params.get("state") else {}
    if params.get("decision") != "allow":
        return _redirect_with(params["redirect_uri"], {"error": "access_denied", **state})
    host, trust = redirect_trust(params["redirect_uri"], request.app.state.settings.mcp_trusted_hosts)
    if trust == "unknown" and params.get("confirm") != "yes":
        return _error("Bitte bestätige, dass du die Verbindung zu dieser unbekannten Adresse selbst gestartet hast.")
    code = secrets.token_urlsafe(32)
    audit.record(db, user_id=uid, actor=user.name if user else "", action="Assistent verbunden", target=f"Assistent {checked.name}", detail=host)
    db.add(
        OAuthCode(
            code_hash=_hash(code),
            client_id=checked.id,
            user_id=uid,
            redirect_uri=params["redirect_uri"],
            code_challenge=params["code_challenge"],
            expires_at=_now() + CODE_TTL,
        )
    )
    db.commit()
    return _redirect_with(params["redirect_uri"], {"code": code, **state})


# --- Tokens ---------------------------------------------------------------------------------------


def _issue(db: Session, client_id: str, user_id: int) -> dict[str, Any]:
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.add(OAuthToken(token_hash=_hash(access), kind="access", client_id=client_id, user_id=user_id, expires_at=_now() + ACCESS_TTL))
    db.add(OAuthToken(token_hash=_hash(refresh), kind="refresh", client_id=client_id, user_id=user_id, expires_at=_now() + REFRESH_TTL))
    db.execute(delete(OAuthToken).where(OAuthToken.expires_at < _now()))
    db.commit()
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TTL.total_seconds()), "refresh_token": refresh, "scope": "finanzen"}


def _token_error(error: str, description: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=400, headers=NO_STORE)


@router.post("/oauth/token")
async def token(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    params = await _form(request)
    grant = params.get("grant_type")
    client_id = params.get("client_id", "")
    if db.get(OAuthClient, client_id) is None:
        return JSONResponse({"error": "invalid_client"}, status_code=401, headers=NO_STORE)
    if grant == "authorization_code":
        row = db.get(OAuthCode, _hash(params.get("code", "")))
        if row is None or row.client_id != client_id or row.expires_at < _now():
            return _token_error("invalid_grant", "Code ungültig oder abgelaufen")
        db.delete(row)  # single use
        if row.redirect_uri != params.get("redirect_uri"):
            db.commit()
            return _token_error("invalid_grant", "redirect_uri passt nicht")
        verifier = params.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not verifier or not secrets.compare_digest(challenge, row.code_challenge):
            db.commit()
            return _token_error("invalid_grant", "PKCE-Prüfung fehlgeschlagen")
        return JSONResponse(_issue(db, client_id, row.user_id), headers=NO_STORE)
    if grant == "refresh_token":
        row = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == _hash(params.get("refresh_token", "")), OAuthToken.kind == "refresh"))
        if row is None or row.client_id != client_id or row.expires_at < _now():
            return _token_error("invalid_grant", "Refresh-Token ungültig")
        user_id = row.user_id
        db.delete(row)  # rotation
        return JSONResponse(_issue(db, client_id, user_id), headers=NO_STORE)
    return _token_error("unsupported_grant_type")


@router.post("/oauth/revoke")
async def revoke(request: Request, db: Session = Depends(get_db)) -> Response:
    params = await _form(request)
    db.execute(delete(OAuthToken).where(OAuthToken.token_hash == _hash(params.get("token", ""))))
    db.commit()
    return Response(status_code=200)


def bearer_user(request: Request, db: Session) -> tuple[User, str] | None:
    """User and client id for a valid access token in the Authorization header."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    row = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == _hash(header[7:].strip()), OAuthToken.kind == "access"))
    if row is None or row.expires_at < _now():
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    row.last_used_at = _now()
    db.commit()
    return user, row.client_id


def challenge_headers(request: Request) -> dict[str, str]:
    base = _base(request)
    return {"WWW-Authenticate": f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'}


def require_bearer(request: Request, db: Session) -> tuple[User, str]:
    found = bearer_user(request, db)
    if found is None:
        raise HTTPException(401, "Nicht angemeldet", headers=challenge_headers(request))
    return found


# --- Connected assistants (for the settings page) -------------------------------------------------

from ..auth.session import current_user  # noqa: E402

api = APIRouter(prefix="/api/mcp", dependencies=[Depends(current_user)])


@api.get("/clients")
def list_clients(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.execute(
        select(OAuthClient, OAuthToken, User)
        .join(OAuthToken, OAuthToken.client_id == OAuthClient.id)
        .join(User, User.id == OAuthToken.user_id)
        .where(OAuthToken.kind == "refresh", OAuthToken.expires_at > _now())
    ).all()
    clients: dict[str, dict] = {}
    for client, tok, user in rows:
        hosts = sorted({redirect_trust(u, ())[0] for u in client.redirect_uris or []})
        entry = clients.setdefault(client.id, {"id": client.id, "name": client.name, "hosts": hosts, "users": set(), "connected_at": tok.created_at, "last_used_at": None})
        entry["users"].add(user.name)
        entry["connected_at"] = min(entry["connected_at"], tok.created_at)
    for client_id, entry in clients.items():
        entry["last_used_at"] = db.scalar(select(OAuthToken.last_used_at).where(OAuthToken.client_id == client_id, OAuthToken.last_used_at.is_not(None)).order_by(OAuthToken.last_used_at.desc()).limit(1))
        entry["users"] = sorted(entry["users"])
    return {"url": f"{_base(request)}/mcp", "clients": sorted(clients.values(), key=lambda c: c["connected_at"], reverse=True)}


@api.delete("/clients/{client_id}", status_code=204)
def disconnect(client_id: str, db: Session = Depends(get_db)) -> Response:
    client = db.get(OAuthClient, client_id)
    if client is None:
        raise HTTPException(404, "Nicht gefunden")
    db.delete(client)  # cascades to codes and tokens
    db.commit()
    return Response(status_code=204)
