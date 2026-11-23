"""JSON API for the frontend."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.session import current_user
from ..config import Settings
from ..db import get_db
from ..models import Person, User
from .schemas import ConfigOut, MeOut, PersonIn, PersonOut

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def avatar_url(user: User | None) -> str | None:
    if user is None or not user.avatar_hash:
        return None
    return f"/avatar/{user.id}?v={user.avatar_hash}"


def person_out(person: Person) -> PersonOut:
    return PersonOut(
        id=person.id,
        name=person.name,
        color=person.color,
        user_id=person.user_id,
        avatar_url=avatar_url(person.user),
        archived=person.archived,
    )


@public.get("/config", response_model=ConfigOut)
def config(request: Request) -> ConfigOut:
    settings: Settings = request.app.state.settings
    return ConfigOut(
        version=settings.version,
        provider_name=settings.oidc_provider_name,
        oidc_enabled=settings.oidc_enabled,
        dev_login=settings.dev_login,
    )


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
        avatar_url=avatar_url(user),
        person_id=user.person.id if user.person else None,
    )


@router.get("/persons", response_model=list[PersonOut])
def list_persons(db: Session = Depends(get_db)) -> list[PersonOut]:
    persons = db.scalars(select(Person).order_by(Person.archived, Person.id)).all()
    return [person_out(p) for p in persons]


@router.post("/persons", response_model=PersonOut, status_code=201)
def create_person(data: PersonIn, db: Session = Depends(get_db)) -> PersonOut:
    person = Person(name=data.name.strip(), color=data.color, archived=data.archived)
    db.add(person)
    db.commit()
    return person_out(person)


@router.put("/persons/{person_id}", response_model=PersonOut)
def update_person(person_id: int, data: PersonIn, db: Session = Depends(get_db)) -> PersonOut:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "Person nicht gefunden")
    person.name = data.name.strip()
    person.color = data.color
    person.archived = data.archived
    db.commit()
    return person_out(person)


@router.delete("/persons/{person_id}", status_code=204)
def delete_person(person_id: int, db: Session = Depends(get_db)) -> Response:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(404, "Person nicht gefunden")
    if person.user_id is not None:
        raise HTTPException(409, "Personen mit eigenem Login lassen sich nur archivieren.")
    db.delete(person)
    db.commit()
    return Response(status_code=204)
