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


@router.get("/positions/compare")
def get_position_compare(
    period: str = "1Y", account_id: int | None = None, person_id: int | None = None, to: date | None = None, db: Session = Depends(get_db)
) -> dict[str, Any]:
    from ..services.positions import compare

    return compare(db, account_id, person_id, _period(period), to)


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


@router.get("/retirement")
def get_retirement(
    person_id: int | None = None,
    retire_on: date | None = None,
    savings: float | None = None,
    inflation: float = 0.02,
    years: int = 25,
    r_low: float | None = None,
    r_mid: float | None = None,
    r_high: float | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retirement projection for the household (default) or one person."""
    from ..models import Person
    from ..services.retirement import Params, projection

    if person_id is not None and db.get(Person, person_id) is None:
        raise HTTPException(404, "Person nicht gefunden")
    if not (-0.05 <= inflation <= 0.15) or not (1 <= years <= 60) or (savings is not None and not (0 <= savings <= 1_000_000)):
        raise HTTPException(422, "Ungültige Annahme")
    returns = {k: v for k, v in (("vorsichtig", r_low), ("mittel", r_mid), ("optimistisch", r_high)) if v is not None}
    if any(not (-0.2 <= v <= 0.3) for v in returns.values()):
        raise HTTPException(422, "Ungültige Rendite")
    return projection(db, person_id, Params(retire_on=retire_on, savings=savings, inflation=inflation, years=years, returns=returns))


@router.get("/freshness")
def get_freshness(db: Session = Depends(get_db)) -> dict[str, Any]:
    """How current the data is (traffic light on the overview)."""
    from ..services.freshness import freshness

    return freshness(db)


@router.post("/accounts/{account_id}/confirm")
def confirm_account(account_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """'Bestand stimmt': nothing has changed since the last import or entry."""
    from ..models import Account
    from ..services.freshness import confirm

    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Konto nicht gefunden")
    confirm(db, account)
    db.commit()
    return {"account_id": account.id, "confirmed_at": account.details["confirmed_at"]}
