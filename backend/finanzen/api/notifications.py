"""Notification settings, push subscriptions and a test message."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.session import current_user
from ..db import get_db
from ..models import NotificationLog, PushSubscription, User
from ..services import notify

router = APIRouter(prefix="/api/notifications", dependencies=[Depends(current_user)])


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(min_length=20, max_length=200)
    auth: str = Field(min_length=8, max_length=100)
    device: str = Field(default="", max_length=200)


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=2000)


def _state(request: Request, db: Session, user: User) -> dict[str, Any]:
    settings = request.app.state.settings
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id).order_by(PushSubscription.created_at)).all()
    recent = db.scalars(select(NotificationLog).where(NotificationLog.user_id == user.id).order_by(NotificationLog.sent_at.desc()).limit(10)).all()
    return {
        "push_available": settings.push_enabled,
        "email_available": settings.email_enabled,
        "vapid_public_key": settings.vapid_public_key if settings.push_enabled else None,
        "email": user.email,
        "events": [{"key": k, "label": e["label"], "channels": e["channels"]} for k, e in notify.EVENTS.items()],
        "prefs": notify.get_prefs(db, user.id),
        "devices": [{"endpoint": s.endpoint, "device": s.device, "created_at": s.created_at, "last_used_at": s.last_used_at} for s in subs],
        "recent": [{"title": n.title, "channels": n.channels, "sent_at": n.sent_at} for n in recent],
    }


@router.get("")
def get_settings(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return _state(request, db, user)


@router.put("/prefs")
def put_prefs(prefs: dict[str, dict[str, Any]], request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    notify.set_prefs(db, user.id, prefs)
    return _state(request, db, user)


@router.post("/subscriptions", status_code=201)
def subscribe(data: SubscriptionIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    if not request.app.state.settings.push_enabled:
        raise HTTPException(422, "Web-Push ist nicht eingerichtet (VAPID-Schlüssel fehlen in der .env).")
    if not data.endpoint.startswith("https://"):
        raise HTTPException(422, "Ungültige Push-Adresse.")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=data.endpoint)
        db.add(sub)
    sub.user_id, sub.p256dh, sub.auth, sub.device = user.id, data.p256dh, data.auth, data.device
    db.commit()
    return _state(request, db, user)


@router.post("/subscriptions/remove")
def unsubscribe(data: EndpointIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint, PushSubscription.user_id == user.id))
    if sub is not None:
        db.delete(sub)
        db.commit()
    return _state(request, db, user)


@router.post("/test")
def test(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    settings = request.app.state.settings
    title, body = "Testnachricht", f"So sehen Benachrichtigungen von Finanzen aus ({datetime.now():%H:%M} Uhr)."
    pushed = notify.deliver_push(db, settings, user, title, body, "/einstellungen")
    mailed = notify.deliver_mail(settings, user, f"Finanzen: {title}", f"{body}\n\n{settings.public_url}")
    if not pushed and not mailed:
        raise HTTPException(422, "Nichts gesendet – kein Gerät für Push angemeldet und keine E-Mail möglich.")
    return {"push": pushed, "email": mailed}


@router.delete("/log", status_code=204)
def clear_log(db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    for row in db.scalars(select(NotificationLog).where(NotificationLog.user_id == user.id)).all():
        db.delete(row)
    db.commit()
    return Response(status_code=204)
