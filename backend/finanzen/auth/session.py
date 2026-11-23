"""Signed session cookie and the current-user dependency."""

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import get_db
from ..models import User

SESSION_COOKIE = "finanzen_session"
SESSION_MAX_AGE = 30 * 24 * 3600


def serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_key, salt=salt)


def set_session(response: Response, settings: Settings, user_id: int) -> None:
    token = serializer(settings, "session").dumps({"uid": user_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")


def session_user_id(request: Request) -> int | None:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = serializer(settings, "session").loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = session_user_id(request)
    user = db.get(User, uid) if uid is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Nur für Admins")
    return user
