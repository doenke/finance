"""Notifications: per-user settings, delivery via web push and e-mail, daily checks and the monthly report."""

import html as html_lib
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .. import kinds
from ..config import Settings
from ..models import Account, BankLogin, Instrument, NotificationLog, NotificationPref, Price, PushSubscription, User, Valuation
from . import mailer, webpush
from .performance import Scope, aggregate, performance

log = logging.getLogger("finanzen.notify")
ZERO = Decimal("0")

# Event definitions: label, channels it can use, defaults (incl. parameters). E-mail is opt-in everywhere.
EVENTS: dict[str, dict[str, Any]] = {
    "bank_error": {"label": "Bankabruf fehlgeschlagen", "channels": ["push", "email"], "defaults": {"push": True, "email": False}},
    "tan_required": {"label": "TAN-Freigabe für den automatischen Abruf nötig", "channels": ["push", "email"], "defaults": {"push": True, "email": False}},
    "maturity": {"label": "Festgeld oder Zinsbindung läuft aus", "channels": ["push", "email"], "defaults": {"push": True, "email": False, "days": 30}},
    "value_change": {
        "label": "Große Veränderung des Nettovermögens",
        "channels": ["push", "email"],
        "defaults": {"push": False, "email": False, "period": "day", "percent": "3", "amount": ""},
    },
    "valuation_due": {"label": "Bewertung oder Kurs fällig", "channels": ["push", "email"], "defaults": {"push": True, "email": False, "months": 13}},
    "monthly_report": {"label": "Monatsbericht", "channels": ["email"], "defaults": {"push": False, "email": False}},
}

# Replaced in tests.
push_sender = webpush.send
mail_sender = mailer.send_mail


def get_prefs(db: Session, user_id: int) -> dict[str, dict[str, Any]]:
    row = db.get(NotificationPref, user_id)
    stored = (row.prefs if row else None) or {}
    return {key: {**ev["defaults"], **(stored.get(key) or {})} for key, ev in EVENTS.items()}


def set_prefs(db: Session, user_id: int, prefs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    clean: dict[str, dict[str, Any]] = {}
    for key, ev in EVENTS.items():
        given = prefs.get(key) or {}
        entry: dict[str, Any] = {}
        for name, default in ev["defaults"].items():
            value = given.get(name, default)
            if isinstance(default, bool):
                value = bool(value) and (name not in ("push", "email") or name in ev["channels"])
            elif isinstance(default, int):
                try:
                    value = max(1, min(int(value), 3650))
                except (TypeError, ValueError):
                    value = default
            elif name == "period":
                value = value if value in ("day", "week") else default
            else:  # decimal thresholds as strings
                try:
                    value = str(Decimal(str(value).replace(",", "."))) if str(value).strip() else ""
                except ArithmeticError:
                    value = default
            entry[name] = value
        clean[key] = entry
    row = db.get(NotificationPref, user_id)
    if row is None:
        db.add(NotificationPref(user_id=user_id, prefs=clean))
    else:
        row.prefs = clean
    db.commit()
    return get_prefs(db, user_id)


def _already_sent(db: Session, user_id: int, key: str, window: timedelta) -> bool:
    since = datetime.now(UTC) - window
    return bool(db.scalar(select(func.count()).select_from(NotificationLog).where(NotificationLog.user_id == user_id, NotificationLog.key == key, NotificationLog.sent_at >= since)))


def deliver_push(db: Session, settings: Settings, user: User, title: str, body: str, url: str) -> int:
    if not settings.push_enabled:
        return 0
    sent = 0
    for sub in db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)).all():
        result = push_sender(
            sub.endpoint,
            sub.p256dh,
            sub.auth,
            {"title": title, "body": body, "url": url},
            public_key=settings.vapid_public_key,
            private_key=settings.vapid_private_key,
            subject=settings.vapid_subject or settings.public_url,
        )
        if result.gone:
            db.delete(sub)
        elif result.ok:
            sub.last_used_at = datetime.now(UTC)
            sent += 1
        else:
            log.warning("push delivery failed with status %s", result.status)
    db.commit()
    return sent


def deliver_mail(settings: Settings, user: User, subject: str, text: str, html: str | None = None) -> bool:
    if not settings.email_enabled or not user.email:
        return False
    try:
        mail_sender(settings, user.email, subject, text, html)
    except Exception:  # noqa: BLE001
        log.exception("sending mail failed")
        return False
    return True


def notify(
    db: Session,
    settings: Settings,
    user: User,
    event: str,
    title: str,
    body: str,
    *,
    url: str = "/",
    key: str | None = None,
    window: timedelta = timedelta(days=1),
    mail_text: str | None = None,
    mail_html: str | None = None,
) -> list[str]:
    """Sends one notification over the channels the user chose for this event. Returns the channels used."""
    prefs = get_prefs(db, user.id)[event]
    key = key or f"{event}:{title}"
    if _already_sent(db, user.id, key, window):
        return []
    channels = []
    if prefs.get("push") and "push" in EVENTS[event]["channels"] and deliver_push(db, settings, user, title, body, url):
        channels.append("push")
    if prefs.get("email") and "email" in EVENTS[event]["channels"]:
        text = mail_text or f"{body}\n\n{settings.public_url}{url}"
        if deliver_mail(settings, user, f"Finanzen: {title}", text, mail_html):
            channels.append("email")
    if channels:
        db.add(NotificationLog(user_id=user.id, event=event, key=key[:200], title=title[:200], body=body, channels=",".join(channels)))
        db.commit()
    return channels


# --- formatting ------------------------------------------------------------------------------------


def eur(value: Decimal | None, signed: bool = False) -> str:
    if value is None:
        return "–"
    q = Decimal(value).quantize(Decimal("0.01"))
    sign = "+" if signed and q > 0 else ("−" if q < 0 else "")
    whole, cents = f"{abs(q):.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{whole},{cents} €"


def pct(value: Decimal | None) -> str:
    if value is None:
        return "–"
    q = (Decimal(value) * 100).quantize(Decimal("0.1"))
    sign = "+" if q > 0 else ("−" if q < 0 else "")
    return f"{sign}{abs(q)}".replace(".", ",") + " %"


def de_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


# --- bank jobs -------------------------------------------------------------------------------------


def bank_job_failed(db: Session, settings: Settings, login: BankLogin, error: str) -> None:
    """Called after an automatic sync ended with an error; tells the owner of the login."""
    if login.user_id is None:
        return
    user = db.get(User, login.user_id)
    if user is None:
        return
    if login.needs_tan:
        notify(
            db, settings, user, "tan_required",
            f"{login.name}: TAN-Freigabe nötig",
            "Die Bank möchte eine neue Freigabe. Öffne Banken und tippe einmal auf „Aktualisieren“.",
            url="/banken", key=f"tan:{login.id}:{date.today()}",
        )
    else:
        notify(db, settings, user, "bank_error", f"{login.name}: Abruf fehlgeschlagen", error[:300] or "Unbekannter Fehler", url="/banken", key=f"bankerr:{login.id}:{date.today()}")


# --- daily checks ----------------------------------------------------------------------------------


def _months_ago(today: date, months: int) -> date:
    y, m = divmod(today.year * 12 + today.month - 1 - months, 12)
    day = min(today.day, 28)
    return date(y, m + 1, day)


def check_maturities(db: Session, settings: Settings, users: list[User], today: date) -> int:
    count = 0
    for account in db.scalars(select(Account).where(Account.closed.is_(False), Account.kind.in_(("festgeld", "kredit")))).all():
        field = "end" if account.kind == "festgeld" else "fixed_until"
        raw = (account.details or {}).get(field)
        try:
            end = date.fromisoformat(str(raw)[:10]) if raw else None
        except ValueError:
            end = None
        if end is None or end < today:
            continue
        what = "Festgeld" if account.kind == "festgeld" else "Zinsbindung"
        left = (end - today).days
        for user in users:
            if left > int(get_prefs(db, user.id)["maturity"]["days"]):
                continue
            title = f"{what} „{account.name}“ endet am {de_date(end)}"
            body = "Heute." if left == 0 else f"Noch {left} Tage." + (" Zeit, sich um die Anschlussfinanzierung zu kümmern." if account.kind == "kredit" else "")
            if notify(db, settings, user, "maturity", title, body, url=f"/konten/{account.id}", key=f"maturity:{account.id}:{end}", window=timedelta(days=3650)):
                count += 1
    return count


def check_valuations(db: Session, settings: Settings, users: list[User], today: date) -> int:
    """Reminds of valuations (pensions, property, other) and manual prices (e.g. STAK) that are getting old."""
    due: list[tuple[str, str, date, str]] = []  # key, title, last date, url
    for account in db.scalars(select(Account).where(Account.closed.is_(False))).all():
        kind = kinds.KINDS.get(account.kind)
        if kind and kind.mode == kinds.VALUATION:
            last = db.scalar(select(func.max(Valuation.date)).where(Valuation.account_id == account.id))
            if last:
                due.append((f"valdue:a{account.id}:{last}", f"Neuer Wert für „{account.name}“?", last, f"/konten/{account.id}"))
    held = db.execute(
        select(Instrument.id, Instrument.name, func.max(Price.date))
        .join(Price, Price.instrument_id == Instrument.id, isouter=True)
        .where(Instrument.price_source == "manual")
        .group_by(Instrument.id, Instrument.name)
    ).all()
    from .valuation import holdings_value

    held_ids: set[int] = set()
    for account in db.scalars(select(Account).where(Account.closed.is_(False))).all():
        kind = kinds.KINDS.get(account.kind)
        if kind and kind.mode == kinds.HOLDINGS:
            _, positions = holdings_value(db, account.id, today)
            held_ids |= {p.instrument_id for p in positions.values() if p.quantity > 0}
    for instrument_id, name, last in held:
        if instrument_id in held_ids and last:
            due.append((f"valdue:i{instrument_id}:{last}", f"Neuer Kurs für „{name}“?", last, f"/wertpapiere/{instrument_id}"))
    count = 0
    for user in users:
        months = int(get_prefs(db, user.id)["valuation_due"]["months"])
        limit = _months_ago(today, months)
        for key, title, last, url in due:
            if last > limit:
                continue
            body = f"Der letzte Stand ist vom {de_date(last)}. Trag den Wert aus der aktuellen Mitteilung ein."
            if notify(db, settings, user, "valuation_due", title, body, url=url, key=key, window=timedelta(days=30)):
                count += 1
    return count


def check_value_change(db: Session, settings: Settings, users: list[User], today: date) -> int:
    agg = aggregate(db, Scope(), None, today)
    if not agg.dates or len(agg.dates) < 2:
        return 0
    net = [a + liab for a, liab in zip(agg.assets, agg.liabilities, strict=True)]
    count = 0
    for user in users:
        prefs = get_prefs(db, user.id)["value_change"]
        if not (prefs["push"] or prefs["email"]):
            continue
        back = 1 if prefs["period"] == "day" else 7
        if len(net) <= back:
            continue
        now, before = net[-1], net[-1 - back]
        change = now - before
        rel = change / abs(before) if before else None
        hit = False
        if prefs.get("percent") and rel is not None and abs(rel) * 100 >= Decimal(prefs["percent"]):
            hit = True
        if prefs.get("amount") and abs(change) >= Decimal(prefs["amount"]):
            hit = True
        if not hit:
            continue
        span = "seit gestern" if back == 1 else "in einer Woche"
        title = f"Nettovermögen {span} {eur(change, signed=True)}"
        body = f"{pct(rel)} auf {eur(now)}."
        if notify(db, settings, user, "value_change", title, body, url="/", key=f"value:{prefs['period']}:{today}", window=timedelta(days=1)):
            count += 1
    return count


def run_daily(settings: Settings, make_session: sessionmaker, today: date | None = None) -> dict[str, int]:
    today = today or date.today()
    result: dict[str, int] = {}
    with make_session() as db:
        users = list(db.scalars(select(User)).all())
        for name, check in (("maturity", check_maturities), ("valuation_due", check_valuations), ("value_change", check_value_change)):
            try:
                result[name] = check(db, settings, users, today)
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("notification check %s failed", name)
    return result


# --- monthly report --------------------------------------------------------------------------------

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def build_report(db: Session, settings: Settings, end: date) -> tuple[str, str, str] | None:
    """Monthly report for the month that ends on `end`: (subject, text, html)."""
    from .valuation import account_value

    agg = aggregate(db, Scope(), None, end)
    if not agg.dates:
        return None
    month_start = end.replace(day=1) - timedelta(days=1)

    def net_at(d: date) -> Decimal | None:
        j = (d - agg.dates[0]).days
        return agg.assets[j] + agg.liabilities[j] if 0 <= j < len(agg.dates) else None

    now = net_at(end)
    before = net_at(month_start)
    year_before = net_at(date(end.year - 1, 12, 31))
    perf = performance(db, Scope(), "ALL", end=end)["periods"]
    month_ret, ytd = perf.get("1M", {}), perf.get("YTD", {})
    moves = []
    for account in db.scalars(select(Account).where(Account.closed.is_(False))).all():
        a, b = account_value(db, account, end).value, account_value(db, account, month_start).value
        if a != b:
            moves.append((account.name, a - b, a))
    moves.sort(key=lambda m: abs(m[1]), reverse=True)
    moves = moves[:5]
    label = f"{MONTHS[end.month - 1]} {end.year}"
    subject = f"Finanzen: Monatsbericht {label}"
    lines = [
        f"Monatsbericht {label}",
        "",
        f"Nettovermögen: {eur(now)}",
        f"Veränderung im Monat: {eur(now - before, signed=True) if before is not None and now is not None else '–'}",
        f"Veränderung seit Jahresbeginn: {eur(now - year_before, signed=True) if year_before is not None and now is not None else '–'}",
        f"Vermögen {eur(agg.assets[-1])} · Schulden {eur(agg.liabilities[-1])}",
        "",
        f"Rendite im Monat (TTWROR): {pct(month_ret.get('ttwror'))}, Gewinn {eur(month_ret.get('gain'), signed=True)}",
        f"Rendite seit Jahresbeginn: {pct(ytd.get('ttwror'))}, Gewinn {eur(ytd.get('gain'), signed=True)}",
    ]
    if moves:
        lines += ["", "Größte Bewegungen:"] + [f"  {name}: {eur(delta, signed=True)} (jetzt {eur(value)})" for name, delta, value in moves]
    lines += ["", settings.public_url]
    text = "\n".join(lines)
    esc = html_lib.escape
    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0'>{esc(name)}</td><td style='padding:4px 0;text-align:right'>{esc(eur(delta, signed=True))}</td></tr>" for name, delta, _ in moves
    )
    html = f"""<!doctype html><html lang="de"><body style="font:15px/1.5 system-ui,sans-serif;color:#1c1f1a;max-width:560px;margin:0 auto;padding:16px">
<h1 style="font-size:20px;margin:0 0 12px">Monatsbericht {esc(label)}</h1>
<p style="font-size:28px;font-weight:700;margin:0">{esc(eur(now))}</p>
<p style="margin:4px 0 16px;color:#5b6157">Nettovermögen · im Monat {esc(eur(now - before, signed=True) if before is not None and now is not None else '–')} · seit Jahresbeginn {esc(eur(now - year_before, signed=True) if year_before is not None and now is not None else '–')}</p>
<table style="border-collapse:collapse;margin-bottom:16px"><tr><td style="padding:4px 12px 4px 0">Rendite im Monat</td><td style="text-align:right">{esc(pct(month_ret.get('ttwror')))}</td></tr>
<tr><td style="padding:4px 12px 4px 0">Rendite seit Jahresbeginn</td><td style="text-align:right">{esc(pct(ytd.get('ttwror')))}</td></tr></table>
{f"<h2 style='font-size:16px;margin:0 0 4px'>Größte Bewegungen</h2><table style='border-collapse:collapse'>{rows}</table>" if moves else ""}
<p style="margin-top:24px"><a href="{esc(settings.public_url)}" style="color:#15803d">Finanzen öffnen</a></p></body></html>"""
    return subject, text, html


def run_report(settings: Settings, make_session: sessionmaker, today: date | None = None) -> int:
    today = today or date.today()
    end = today.replace(day=1) - timedelta(days=1)
    sent = 0
    with make_session() as db:
        report = build_report(db, settings, end)
        if report is None:
            return 0
        subject, text, html = report
        for user in db.scalars(select(User)).all():
            if not get_prefs(db, user.id)["monthly_report"]["email"]:
                continue
            key = f"report:{end:%Y-%m}"
            if _already_sent(db, user.id, key, timedelta(days=40)):
                continue
            if deliver_mail(settings, user, subject, text, html):
                db.add(NotificationLog(user_id=user.id, event="monthly_report", key=key, title=subject[:200], body="", channels="email"))
                db.commit()
                sent += 1
    return sent
