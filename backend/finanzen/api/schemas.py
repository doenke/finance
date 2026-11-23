"""Pydantic schemas for the JSON API."""

from pydantic import BaseModel, Field


class PersonOut(BaseModel):
    id: int
    name: str
    color: str
    user_id: int | None
    avatar_url: str | None
    archived: bool


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#15803d", pattern=r"^#[0-9a-fA-F]{6}$")
    archived: bool = False


class MeOut(BaseModel):
    id: int
    name: str
    email: str
    is_admin: bool
    avatar_url: str | None
    person_id: int | None


class ConfigOut(BaseModel):
    version: str
    provider_name: str
    oidc_enabled: bool
    dev_login: bool
