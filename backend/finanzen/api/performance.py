"""Performance, net worth and benchmark endpoints."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.session import current_user
from ..db import get_db
from ..services.performance import PERIODS, Scope, benchmark, breakdown, net_worth, performance

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def _period(period: str) -> str:
    if period not in PERIODS:
        raise HTTPException(422, "Unbekannter Zeitraum")
    return period


@router.get("/performance")
def get_performance(
    period: str = "ALL",
    account_id: int | None = None,
    asset_class: str | None = None,
    person_id: int | None = None,
    to: date | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return performance(db, Scope(account_id, asset_class, person_id), _period(period), to)


@router.get("/performance/breakdown")
def get_breakdown(period: str = "1Y", person_id: int | None = None, to: date | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return breakdown(db, person_id, _period(period), to)


@router.get("/liquidity")
def get_liquidity(person_id: int | None = None, to: date | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    from ..services.liquidity import liquidity

    return liquidity(db, person_id, to)


@router.get("/networth")
def get_networth(period: str = "1Y", person_id: int | None = None, to: date | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return net_worth(db, Scope(person_id=person_id), _period(period), to)


@router.get("/benchmark/{instrument_id}")
def get_benchmark(instrument_id: int, start: date, end: date | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return benchmark(db, instrument_id, start, end or date.today())
