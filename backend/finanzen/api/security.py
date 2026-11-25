"""Own sessions (devices), user administration (log out, lock) and the audit log."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.session import admin_user, current_session, current_user, revoke_user_access
from ..db import get_db
from ..models import AuditEntry, OAuthToken, User, UserSession

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
admin = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_user)])


# --- Own devices ----------------------------------------------------------------------------------


@router.get("/sessions")
def list_sessions(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    own = current_session(request, db)
    rows = db.scalars(select(UserSession).where(UserSession.user_id == user.id).order_by(UserSession.last_seen_at.desc())).all()
    return [
        {"id": s.id, "user_agent": s.user_agent, "created_at": s.created_at, "last_seen_at": s.last_seen_at, "current": own is not None and s.id == own.id}
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def end_one(session_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    row = db.get(UserSession, session_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Gerät nicht gefunden")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/sessions/revoke-others")
def end_others(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, int]:
    own = current_session(request, db)
    ended = revoke_user_access(db, user.id, keep_session_id=own.id if own else None, include_tokens=False)
    db.commit()
    return {"ended": ended}


# --- Audit log ------------------------------------------------------------------------------------


@router.get("/audit")
def audit_log(before: int | None = None, limit: int = 100, db: Session = Depends(get_db)) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    stmt = select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit + 1)
    if before:
        stmt = stmt.where(AuditEntry.id < before)
    rows = db.scalars(stmt).all()
    items = [
        {"id": e.id, "at": e.at, "actor": e.actor, "via": e.via, "client": e.client, "action": e.action, "target": e.target, "detail": e.detail}
        for e in rows[:limit]
    ]
    return {"items": items, "more": len(rows) > limit}


# --- User administration --------------------------------------------------------------------------


class DisabledIn(BaseModel):
    disabled: bool


def _user_out(db: Session, u: User) -> dict[str, Any]:
    now = datetime.now().astimezone()
    sessions = db.scalar(select(func.count()).select_from(UserSession).where(UserSession.user_id == u.id, UserSession.expires_at > now)) or 0
    tokens = db.scalar(select(func.count()).select_from(OAuthToken).where(OAuthToken.user_id == u.id, OAuthToken.kind == "refresh", OAuthToken.expires_at > now)) or 0
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "is_admin": u.is_admin,
        "disabled": u.disabled,
        "last_login_at": u.last_login_at,
        "sessions": sessions,
        "assistants": tokens,
    }


@admin.get("/users")
def list_users(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_user_out(db, u) for u in db.scalars(select(User).order_by(User.name)).all()]


def _other_user(db: Session, user_id: int, me: User) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if target.id == me.id:
        raise HTTPException(409, "Das bist du selbst – nutze „Abmelden“ bzw. „Alle anderen Geräte abmelden“.")
    return target


@admin.post("/users/{user_id}/logout")
def logout_user(user_id: int, db: Session = Depends(get_db), me: User = Depends(admin_user)) -> dict[str, Any]:
    target = _other_user(db, user_id, me)
    revoke_user_access(db, target.id)
    db.commit()
    return _user_out(db, target)


@admin.put("/users/{user_id}/disabled")
def set_disabled(user_id: int, data: DisabledIn, request: Request, db: Session = Depends(get_db), me: User = Depends(admin_user)) -> dict[str, Any]:
    target = _other_user(db, user_id, me)
    target.disabled = data.disabled
    if data.disabled:
        revoke_user_access(db, target.id)
    db.commit()
    request.state.audit_action = "Benutzer gesperrt" if data.disabled else "Benutzer entsperrt"
    return _user_out(db, target)
