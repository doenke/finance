"""Server-side sessions behind a signed cookie, and the current-user dependency.

The cookie carries a random token (signed, so tampering is cheap to reject); the database stores only its
hash. Logging out deletes the row, so a copied cookie stops working too. Locked users have no sessions.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import OAuthCode, OAuthToken, User, UserSession

SESSION_COOKIE = "finanzen_session"
SESSION_MAX_AGE = 30 * 24 * 3600
TOUCH_EVERY = timedelta(minutes=5)


def serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_key, salt=salt)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def set_session(response: Response, request: Request, db: Session, user: User) -> UserSession:
    """Creates a session row for the user and sets the cookie. Commits."""
    settings: Settings = request.app.state.settings
    token = secrets.token_urlsafe(32)
    row = UserSession(
        token_hash=_hash(token),
        user_id=user.id,
        user_agent=(request.headers.get("user-agent") or "")[:200],
        expires_at=_now() + timedelta(seconds=SESSION_MAX_AGE),
    )
    db.add(row)
    db.execute(delete(UserSession).where(UserSession.expires_at < _now()))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        serializer(settings, "session").dumps({"sid": token}),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return row


def clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")


def _token(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = serializer(request.app.state.settings, "session").loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    sid = data.get("sid") if isinstance(data, dict) else None
    return sid if isinstance(sid, str) and sid else None


def current_session(request: Request, db: Session) -> UserSession | None:
    """The valid session of this request (not expired, user not locked), or None."""
    token = _token(request)
    if token is None:
        return None
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if row is None or row.expires_at < _now():
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    if _now() - row.last_seen_at > TOUCH_EVERY:
        row.last_seen_at = _now()
        db.commit()
    return row


def session_user(request: Request, db: Session) -> User | None:
    row = current_session(request, db)
    user = db.get(User, row.user_id) if row else None
    if user is not None:
        # Read by the audit middleware once the request is done.
        request.state.audit_user = (user.id, user.name)
    return user


def end_session(request: Request, db: Session) -> None:
    """Deletes this request's session row (logout)."""
    token = _token(request)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
        db.commit()


def revoke_user_access(db: Session, user_id: int, keep_session_id: int | None = None, include_tokens: bool = True) -> int:
    """Ends all sessions of a user (except one) and, by default, all MCP tokens. Does not commit. Returns the number of sessions ended."""
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_session_id is not None:
        stmt = stmt.where(UserSession.id != keep_session_id)
    ended = db.execute(stmt).rowcount or 0
    if include_tokens:
        db.execute(delete(OAuthToken).where(OAuthToken.user_id == user_id))
        db.execute(delete(OAuthCode).where(OAuthCode.user_id == user_id))
    return ended


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Nur für Admins")
    return user
