"""What-if calculations for loans: prepayments, installment changes and follow-up interest."""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Account
from .loan import Prepayment, Row, add_months, balance_at, expand_planned, schedule
from .valuation import _dec, _date, loan_prepayments, loan_terms

ZERO = Decimal("0")


@dataclass
class ScenarioSpec:
    name: str
    include_planned: bool = True
    extra_prepayments: list[dict] = field(default_factory=list)  # {date, amount, repeat, until}
    installment: Decimal | None = None
    installment_from: date | None = None
    followup_rate: Decimal | None = None  # None = keep the contract assumption


@dataclass
class ScenarioResult:
    name: str
    rows: list[Row]
    end_date: date | None
    interest_remaining: Decimal
    payments_remaining: Decimal
    prepayments_remaining: Decimal
    balance_at_fixed_until: Decimal | None
    balance_today: Decimal


def spec_from_dict(data: dict) -> ScenarioSpec:
    return ScenarioSpec(
        name=str(data.get("name") or "Szenario")[:60],
        include_planned=bool(data.get("include_planned", True)),
        extra_prepayments=[p for p in data.get("extra_prepayments") or [] if p.get("date") and p.get("amount")],
        installment=_dec(data.get("installment")) or None,
        installment_from=_date(data.get("installment_from")),
        followup_rate=_dec(data.get("followup_rate")) if data.get("followup_rate") not in (None, "") else None,
    )


def run_scenario(db: Session, account: Account, spec: ScenarioSpec, today: date | None = None) -> ScenarioResult | None:
    from sqlalchemy import select

    from ..models import BalanceSnapshot

    terms = loan_terms(account)
    if terms is None:
        return None
    today = today or date.today()
    if spec.followup_rate is not None:
        terms = replace(terms, followup_rate=spec.followup_rate, fixed_until=terms.fixed_until or today)
    horizon = add_months(today, 12 * 80)
    prepayments: list[Prepayment] = loan_prepayments(db, account, include_planned=spec.include_planned, until=horizon)
    prepayments += expand_planned(spec.extra_prepayments, horizon)
    changes = [(spec.installment_from or today, spec.installment)] if spec.installment else None
    snap = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id).order_by(BalanceSnapshot.date.desc()).limit(1))
    if snap:
        start, start_date = abs(snap.amount), snap.date
        rows = schedule(terms, prepayments, start_balance=start, start_date=start_date, installment_changes=changes)
    else:
        start, start_date = terms.principal, terms.disbursed_on
        rows = schedule(terms, prepayments, installment_changes=changes)
    future = [r for r in rows if r.date > today]
    return ScenarioResult(
        name=spec.name,
        rows=rows,
        end_date=rows[-1].date if rows and rows[-1].balance <= 0 else None,
        interest_remaining=sum((r.interest for r in future), ZERO),
        payments_remaining=sum((r.payment for r in future), ZERO),
        prepayments_remaining=sum((r.prepayment for r in future), ZERO),
        balance_at_fixed_until=balance_at(rows, start, terms.fixed_until) if terms.fixed_until else None,
        balance_today=balance_at(rows, start, today) if start_date <= today else start,
    )
