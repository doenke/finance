"""Create or update users from login claims."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Person, User

PERSON_COLORS = ["#15803d", "#2563eb", "#c2410c", "#7c3aed", "#0f766e", "#be185d"]


def _groups(claims: dict[str, Any]) -> list[str]:
    groups = claims.get("groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return [str(g) for g in groups]


def upsert_user(db: Session, claims: dict[str, Any], admin_group: str) -> User:
    sub = str(claims["sub"])
    user = db.scalar(select(User).where(User.sub == sub))
    if user is None:
        user = User(sub=sub)
        db.add(user)
    user.name = str(claims.get("name") or claims.get("preferred_username") or claims.get("email") or "Unbekannt")
    user.email = str(claims.get("email") or "")
    user.is_admin = admin_group in _groups(claims)
    user.last_login_at = datetime.now(UTC)
    db.flush()
    ensure_person(db, user)
    return user


def ensure_person(db: Session, user: User) -> Person:
    """Each user gets a household member entry on first login (first name as display name)."""
    person = db.scalar(select(Person).where(Person.user_id == user.id))
    if person is None:
        count = db.query(Person).count()
        first_name = user.name.split(" ")[0] if user.name else "Ich"
        person = Person(name=first_name, user_id=user.id, color=PERSON_COLORS[count % len(PERSON_COLORS)])
        db.add(person)
        db.flush()
    return person
