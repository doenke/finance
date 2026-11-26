"""How current the data is: one traffic light for the overview, with the reasons behind it.

Every source has its own expectation:
- prices that are fetched automatically: a few trading days,
- bank logins with FinTS: a sync within a week and without errors,
- cash accounts maintained by CSV or by hand: monthly (everyday accounts) or quarterly (savings accounts),
- depots and crypto without a bank sync: they only change with trades – a trade or a confirmation
  ("Bestand stimmt") within half a year; with a savings plan (regular monthly buys) the next execution
  is expected every month, whether or not the depot comes via FinTS,
- valued assets (pensions, real estate, manual prices): a statement about once a year.
"""

from datetime import UTC, date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, BalanceSnapshot, BankLogin, Instrument, Price, Trade, Transaction, Valuation
from .cashflow import role_of
from .valuation import holdings_value

GREEN, YELLOW, RED = "green", "yellow", "red"
_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}


def _weekdays_between(a: date, b: date) -> int:
    """Trading days (Mon–Fri) after a up to and including b."""
    days, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def _grade(age: int, yellow: int, red: int) -> str:
    return GREEN if age <= yellow else YELLOW if age <= red else RED


def _de(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "–"


def savings_plan(trade_dates: list[date], today: date) -> bool:
    """Regular buys about once a month in the last half year (at least four, gaps of 20–40 days)."""
    recent = sorted(d for d in trade_dates if d >= today - timedelta(days=190))
    if len(recent) < 4:
        return False
    gaps = [(b - a).days for a, b in zip(recent, recent[1:], strict=False)]
    monthly = sum(1 for g in gaps if 20 <= g <= 40)
    return monthly >= len(gaps) * 0.7


def freshness(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    items: list[dict] = []
    accounts = db.scalars(select(Account).where(Account.closed.is_(False)).order_by(Account.name)).all()
    logins = {bl.id: bl for bl in db.scalars(select(BankLogin)).all()}

    # bank logins with FinTS that have linked accounts
    used_logins = {a.bank_login_id for a in accounts if a.bank_login_id}
    for lid in sorted(used_logins):
        bl = logins.get(lid)
        if bl is None:
            continue
        last = bl.last_sync_at.astimezone(UTC).date() if bl.last_sync_at else None
        age = (today - last).days if last else 10**6
        status = _grade(age, 7, 30)
        message = f"zuletzt abgerufen am {_de(last)}" if last else "noch nie abgerufen"
        if bl.last_error and status == GREEN:
            status = YELLOW
        if bl.last_error:
            message += " – beim letzten Abruf gab es Fehler"
        items.append({"area": "bank", "name": bl.name, "status": status, "last": last, "message": message, "url": "/banken", "login_id": bl.id})

    # prices fetched automatically for instruments that are held
    held: dict[int, list[str]] = {}
    for a in accounts:
        kind = kinds.KINDS.get(a.kind)
        if kind and kind.mode == kinds.HOLDINGS:
            _, positions = holdings_value(db, a.id, today)
            for p in positions.values():
                if p.quantity > 0:
                    held.setdefault(p.instrument_id, []).append(a.name)
    if held:
        last_prices = dict(db.execute(select(Price.instrument_id, func.max(Price.date)).where(Price.instrument_id.in_(held)).group_by(Price.instrument_id)).all())
        for inst in db.scalars(select(Instrument).where(Instrument.id.in_(held))).all():
            last = last_prices.get(inst.id)
            if inst.price_source == "manual":
                age = (today - last).days if last else 10**6
                status = _grade(age, 400, 730)
                items.append({"area": "valuation", "name": inst.name, "status": status, "last": last, "message": f"Kurs von Hand gepflegt, Stand {_de(last)}", "url": f"/wertpapiere/{inst.id}"})
                continue
            if inst.kind == "crypto":  # traded every day
                age = (today - last).days if last else 10**6
                status = _grade(age, 2, 7)
            else:
                age = _weekdays_between(last, today) if last else 10**6
                status = _grade(age, 3, 10)
            items.append({"area": "prices", "name": inst.name, "status": status, "last": last, "message": f"Kurs vom {_de(last)}", "url": f"/wertpapiere/{inst.id}"})

    # settlement accounts of depots/crypto only change with trades: they follow the depot rhythm
    settlement_ids = {a.settlement_account_id for a in accounts if a.settlement_account_id}
    for a in accounts:
        kind = kinds.KINDS.get(a.kind)
        if kind is None or kind.mode in (kinds.LOAN, kinds.DEPOSIT):
            continue  # computed from the contract
        details = a.details or {}
        if kind.mode == kinds.HOLDINGS:
            trade_dates = list(db.scalars(select(Trade.date).where(Trade.account_id == a.id, Trade.type.in_(("buy", "sell", "deliver_in", "deliver_out")))).all())
            last_trade = max(trade_dates, default=None)
            confirmed = _parse(details.get("confirmed_at"))
            if savings_plan(trade_dates, today):
                age = (today - last_trade).days
                items.append({"area": "holdings", "name": a.name, "status": _grade(age, 40, 75), "last": last_trade, "message": f"Sparplan – letzte Ausführung am {_de(last_trade)}", "url": f"/konten/{a.id}", "account_id": a.id})
                continue
            if a.bank_login_id or a.kind == "stak":
                continue  # positions come from the bank / STAK shares: their manually kept price is checked above
            last = max((d for d in (last_trade, confirmed) if d), default=None)
            age = (today - last).days if last else 10**6
            what = "Bestand bestätigt" if confirmed and confirmed == last else "letzte Transaktion"
            items.append({"area": "holdings", "name": a.name, "status": _grade(age, 183, 365), "last": last, "message": f"{what} am {_de(last)}" if last else "noch keine Transaktionen", "url": f"/konten/{a.id}", "account_id": a.id, "confirmable": True})
        elif kind.mode == kinds.CASH:
            if a.bank_login_id:
                continue
            last_balance = db.scalar(select(func.max(BalanceSnapshot.date)).where(BalanceSnapshot.account_id == a.id))
            last_tx = db.scalar(select(func.max(Transaction.booking_date)).where(Transaction.account_id == a.id))
            confirmed = _parse(details.get("confirmed_at"))
            last = max((d for d in (last_balance, last_tx, confirmed) if d), default=None)
            age = (today - last).days if last else 10**6
            yellow, red = (183, 365) if a.id in settlement_ids else (35, 90) if role_of(a) == "spending" else (95, 185)
            items.append({"area": "manual", "name": a.name, "status": _grade(age, yellow, red), "last": last, "message": f"Daten bis {_de(last)} (Import oder von Hand)" if last else "noch keine Daten", "url": f"/konten/{a.id}", "account_id": a.id, "confirmable": True})
        else:  # valued assets
            last = db.scalar(select(func.max(Valuation.date)).where(Valuation.account_id == a.id))
            if a.kind == "altersvorsorge":
                last = max((d for d in (last, _parse(details.get("info_date"))) if d), default=None)
                if last is None and details.get("expected_pension"):
                    continue  # a pension forecast without a value of its own
            last = max((d for d in (last, _parse(details.get("confirmed_at"))) if d), default=None)
            age = (today - last).days if last else 10**6
            items.append({"area": "valuation", "name": a.name, "status": _grade(age, 400, 730), "last": last, "message": f"Stand vom {_de(last)}" if last else "noch kein Stand", "url": f"/konten/{a.id}", "account_id": a.id, "confirmable": True})

    worst = max((i["status"] for i in items), key=lambda s: _ORDER[s], default=GREEN)
    items.sort(key=lambda i: (-_ORDER[i["status"]], i["area"], i["name"]))
    counts = {s: sum(1 for i in items if i["status"] == s) for s in (GREEN, YELLOW, RED)}
    return {"status": worst, "counts": counts, "items": items, "today": today}


def _parse(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def confirm(db: Session, account: Account, today: date | None = None) -> None:
    """'Bestand stimmt': nothing changed since the last import – counts as current."""
    account.details = {**(account.details or {}), "confirmed_at": (today or date.today()).isoformat()}
