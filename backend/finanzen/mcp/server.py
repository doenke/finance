"""MCP server (Streamable HTTP, JSON responses) on /mcp.

Tools let an assistant read the household's finances and add accounts, valuations, bookings, balances and
portfolio transactions. Nothing can be deleted through MCP.
"""

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cache, kinds
from ..api import accounts as acc_api
from ..db import get_db
from ..models import Account, Instrument, OAuthClient, Person, Trade, Transaction, User, Valuation
from ..services import audit
from ..services.performance import PERIODS, Scope, net_worth, performance
from .oauth import challenge_headers, require_bearer

log = logging.getLogger("finanzen.mcp")
router = APIRouter()

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "finanzen", "title": "Finanzen", "version": "1"}
INSTRUCTIONS = (
    "Finanzen ist der Vermögensüberblick eines Haushalts (Konten, Depots, Immobilien, Kredite, Altersvorsorge). "
    "Beträge in Euro als Dezimalzahl mit Punkt (z. B. 1234.56), Datumsangaben als YYYY-MM-DD. "
    "Vor dem Anlegen eines Kontos mit list_accounts prüfen, ob es schon existiert. "
    "Altersvorsorge-Verträge: Konto der Art 'altersvorsorge', Wert aus der Jahresmitteilung per add_valuation, "
    "Beiträge per add_transaction mit kind 'contribution' (nur der Sparanteil, keine Kosten für Berufsunfähigkeit)."
)


def _json(value: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, date):
            return o.isoformat()
        return str(o)

    return json.dumps(value, default=default, ensure_ascii=False, indent=1)


class ToolError(Exception):
    pass


def _person_id(db: Session, user: User, value: Any) -> int:
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        person = db.get(Person, int(value))
    else:
        person = next((p for p in db.scalars(select(Person)).all() if p.name.lower() == str(value).strip().lower()), None)
    if person is None:
        raise ToolError(f"Person „{value}“ nicht gefunden – siehe list_persons.")
    return person.id


def _owners(db: Session, user: User, owners: list[dict] | None) -> list[acc_api.OwnerIn]:
    if not owners:
        return []
    return [acc_api.OwnerIn(person_id=_person_id(db, user, o.get("person")), share=Decimal(str(o.get("share", 1)))) for o in owners]


def _account_summary(db: Session, a: Account, names: dict[int, str]) -> dict:
    out = acc_api.account_out(db, a, date.today())
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "kind_label": out.kind_label,
        "institution": a.institution,
        "value": out.value,
        "value_as_of": out.value_as_of,
        "closed": a.closed,
        "owners": [{"person": names.get(o.person_id, o.person_id), "share": o.share} for o in a.owners],
    }


# --- Tools ----------------------------------------------------------------------------------------


def t_list_persons(db: Session, user: User, args: dict) -> Any:
    return [{"id": p.id, "name": p.name, "has_login": p.user_id is not None, "archived": p.archived} for p in db.scalars(select(Person).order_by(Person.id)).all()]


def t_list_account_kinds(db: Session, user: User, args: dict) -> Any:
    hints = {
        "giro": "Girokonto: Kontostände (add_balance) und Umsätze",
        "tagesgeld": "Tagesgeld: wie Girokonto",
        "verrechnung": "Verrechnungskonto eines Depots",
        "festgeld": "details: amount, rate (Prozent), start, end",
        "kreditkarte": "Kreditkarte: Saldo negativ",
        "depot": "Wertpapiere über add_trade",
        "krypto": "Kryptowährungen über add_trade",
        "stak": "STAK-Anteile über add_trade, Kurse manuell",
        "edelmetall": "Gold/Silber über add_trade",
        "immobilie": "details: purchase_price, purchase_costs, purchase_date, usage (self|rented); Werte per add_valuation",
        "altersvorsorge": "details: product (riester|ruerup|bav|rente|leben|bauspar|other), contract_no, expected_pension, payout_start; Werte per add_valuation, Beiträge per add_transaction kind=contribution",
        "sonstiges": "frei, Werte per add_valuation",
        "kredit": "details: principal, disbursed_on, rate, first_payment, installment oder initial_repayment, fixed_until, …",
    }
    return [{"kind": k.key, "label": k.label, "hint": hints.get(k.key, "")} for k in kinds.KINDS.values()]


def t_list_accounts(db: Session, user: User, args: dict) -> Any:
    names = {p.id: p.name for p in db.scalars(select(Person)).all()}
    rows = db.scalars(select(Account).order_by(Account.closed, Account.name)).all()
    return [_account_summary(db, a, names) for a in rows if args.get("include_closed") or not a.closed]


def t_get_account(db: Session, user: User, args: dict) -> Any:
    account = db.get(Account, int(args["account_id"]))
    if account is None:
        raise ToolError("Konto nicht gefunden.")
    names = {p.id: p.name for p in db.scalars(select(Person)).all()}
    result = _account_summary(db, account, names)
    result["details"] = {k: v for k, v in (account.details or {}).items() if k not in ("fints",)}
    result["notes"] = account.notes
    result["valuations"] = [
        {"date": v.date, "value": v.value, "note": v.note}
        for v in db.scalars(select(Valuation).where(Valuation.account_id == account.id).order_by(Valuation.date.desc()).limit(20)).all()
    ]
    result["recent_transactions"] = [
        {"date": t.booking_date, "amount": t.amount, "kind": t.kind, "counterparty": t.counterparty, "purpose": t.purpose}
        for t in db.scalars(select(Transaction).where(Transaction.account_id == account.id).order_by(Transaction.booking_date.desc()).limit(20)).all()
    ]
    if kinds.KINDS[account.kind].mode == kinds.HOLDINGS:
        from ..services.fx import FxConverter
        from ..services.valuation import holdings_value, position_value

        today = date.today()
        fx = FxConverter(db)
        _, pos = holdings_value(db, account.id, today, fx)
        result["positions"] = []
        for p in pos.values():
            if not p.quantity:
                continue
            inst = db.get(Instrument, p.instrument_id)
            priced = position_value(db, inst, p.quantity, today, fx)
            cost = p.cost.quantize(Decimal("0.01"))
            entry = {"instrument": inst.name, "isin": inst.isin, "quantity": p.quantity, "cost": cost, "price_source": inst.price_source}
            if priced:
                entry.update({"price": priced[1], "price_date": priced[2], "value": priced[0], "gain": (priced[0] - cost).quantize(Decimal("0.01"))})
            result["positions"].append(entry)
    return result


def t_create_account(db: Session, user: User, args: dict) -> Any:
    data = acc_api.AccountIn(
        name=args["name"],
        kind=args["kind"],
        institution=args.get("institution", ""),
        iban=args.get("iban", ""),
        opened_on=args.get("opened_on"),
        notes=args.get("notes", ""),
        details=args.get("details") or {},
        owners=_owners(db, user, args.get("owners")),
    )
    out = acc_api.create_account(data, db, user)
    return {"created": True, "account_id": out.id, "name": out.name, "kind": out.kind}


def t_update_account(db: Session, user: User, args: dict) -> Any:
    account = db.get(Account, int(args["account_id"]))
    if account is None:
        raise ToolError("Konto nicht gefunden.")
    details = dict(account.details or {})
    details.update(args.get("details") or {})
    data = acc_api.AccountIn(
        name=args.get("name", account.name),
        kind=account.kind,
        asset_class=account.asset_class,
        institution=args.get("institution", account.institution),
        iban=account.iban,
        currency=account.currency,
        opened_on=args.get("opened_on", account.opened_on),
        closed=args.get("closed", account.closed),
        notes=args.get("notes", account.notes),
        details=details,
        settlement_account_id=account.settlement_account_id,
        owners=_owners(db, user, args.get("owners")) or [acc_api.OwnerIn(person_id=o.person_id, share=o.share) for o in account.owners],
    )
    out = acc_api.update_account(account.id, data, db, user)
    return {"updated": True, "account_id": out.id}


def t_add_valuation(db: Session, user: User, args: dict) -> Any:
    out = acc_api.upsert_valuation(int(args["account_id"]), acc_api.ValuationIn(date=args["date"], value=Decimal(str(args["value"])), note=args.get("note", "")), db)
    return {"saved": True, "valuation_id": out.id, "date": out.date, "value": out.value}


def t_add_balance(db: Session, user: User, args: dict) -> Any:
    out = acc_api.upsert_balance(int(args["account_id"]), acc_api.BalanceIn(date=args["date"], amount=Decimal(str(args["amount"]))), db)
    return {"saved": True, "balance_id": out.id}


def t_add_transaction(db: Session, user: User, args: dict) -> Any:
    data = acc_api.TransactionIn(
        booking_date=args["date"],
        amount=Decimal(str(args["amount"])),
        kind=args.get("kind", "other"),
        counterparty=args.get("counterparty", ""),
        purpose=args.get("purpose", ""),
    )
    out = acc_api.create_transaction(int(args["account_id"]), data, db)
    return {"saved": True, "transaction_id": out.id}


def t_add_trade(db: Session, user: User, args: dict) -> Any:
    instrument_id = args.get("instrument_id")
    if not instrument_id and (args.get("isin") or args.get("instrument_name")):
        isin = (args.get("isin") or "").strip().upper() or None
        inst = db.scalar(select(Instrument).where(Instrument.isin == isin)) if isin else None
        if inst is None and args.get("instrument_name"):
            inst = db.scalar(select(Instrument).where(Instrument.name == args["instrument_name"]))
        if inst is None:
            symbol = None
            if isin:
                from ..services.prices import SOURCES, PriceSourceError

                try:
                    symbol = SOURCES["onvista"].find_by_isin(isin)
                except PriceSourceError:
                    symbol = None
            inst = Instrument(
                kind=args.get("instrument_kind", "stock"),
                name=args.get("instrument_name") or isin or "Wertpapier",
                isin=isin,
                currency="EUR",
                price_source="onvista" if symbol else "manual",
                price_symbol=symbol,
                details={},
            )
            db.add(inst)
            db.commit()
            if symbol:
                # load the price history right away, like the app does for new instruments
                from ..db import make_sessionmaker
                from ..services.sync import sync_instrument_in_background

                sync_instrument_in_background(make_sessionmaker(db.get_bind()), inst.id)
        instrument_id = inst.id
    data = acc_api.TradeIn(
        date=args["date"],
        type=args["type"],
        instrument_id=instrument_id,
        quantity=Decimal(str(args.get("quantity") or 0)),
        price=Decimal(str(args["price"])) if args.get("price") not in (None, "") else None,
        amount=Decimal(str(args.get("amount") or 0)),
        fees=Decimal(str(args.get("fees") or 0)),
        taxes=Decimal(str(args.get("taxes") or 0)),
        note=args.get("note", ""),
    )
    out = acc_api.create_trade(int(args["account_id"]), data, db)
    return {"saved": True, "trade_id": out.id, "instrument_id": instrument_id}


def t_get_net_worth(db: Session, user: User, args: dict) -> Any:
    person = _person_id(db, user, args["person"]) if args.get("person") else None
    data = net_worth(db, Scope(person_id=person), "1Y")
    from ..services.liquidity import liquidity

    liq = liquidity(db, person)
    bound = [{"name": i["name"], "value": i["value"], "free_from": i["free_from"], "reason": i["free_reason"]} for i in liq["items"] if i["bucket"] == "bound"]
    return {
        "current": data.get("current"),
        "available": liq["available"],
        "bound": liq["bound"],
        "bound_items": bound,
        "as_of": date.today(),
    }


def t_get_performance(db: Session, user: User, args: dict) -> Any:
    period = args.get("period", "1Y")
    if period not in PERIODS:
        raise ToolError(f"period muss eines von {PERIODS} sein.")
    person = _person_id(db, user, args["person"]) if args.get("person") else None
    data = performance(db, Scope(account_id=args.get("account_id"), person_id=person), period)
    return {"from": data.get("from"), "to": data.get("to"), "summary": data.get("summary"), "periods": data.get("periods")}


def t_get_holding_period(db: Session, user: User, args: dict) -> Any:
    on = date.fromisoformat(args["on"]) if args.get("on") else None
    data = acc_api.holding_period(int(args["account_id"]), on, db).model_dump()
    for p in data["positions"]:
        p["instrument"] = {k: p["instrument"][k] for k in ("id", "name", "isin", "unit")}
    return data


def t_list_trades(db: Session, user: User, args: dict) -> Any:
    account = db.get(Account, int(args["account_id"]))
    if account is None:
        raise ToolError("Konto nicht gefunden.")
    if kinds.KINDS[account.kind].mode != kinds.HOLDINGS:
        raise ToolError("Wertpapier-Buchungen gibt es nur bei Depots, Krypto, Edelmetallen und Beteiligungen.")
    stmt = select(Trade).where(Trade.account_id == account.id)
    if args.get("from"):
        stmt = stmt.where(Trade.date >= date.fromisoformat(args["from"]))
    if args.get("to"):
        stmt = stmt.where(Trade.date <= date.fromisoformat(args["to"]))
    if args.get("type"):
        stmt = stmt.where(Trade.type == args["type"])
    if args.get("isin"):
        stmt = stmt.join(Instrument, Trade.instrument_id == Instrument.id).where(Instrument.isin == str(args["isin"]).strip().upper())
    limit = max(1, min(int(args.get("limit") or 200), 1000))
    rows = db.scalars(stmt.order_by(Trade.date.desc(), Trade.id.desc()).limit(limit + 1)).all()
    instruments: dict[int, Instrument | None] = {}

    def inst(iid: int | None) -> dict | None:
        if iid is None:
            return None
        if iid not in instruments:
            instruments[iid] = db.get(Instrument, iid)
        i = instruments[iid]
        return {"id": iid, "name": i.name, "isin": i.isin} if i else {"id": iid}

    return {
        "account": account.name,
        "count": min(len(rows), limit),
        "more": len(rows) > limit,
        "trades": [
            {
                "id": t.id,
                "date": t.date,
                "type": t.type,
                "instrument": inst(t.instrument_id),
                "quantity": t.quantity,
                "price": t.price,
                "amount": t.amount,
                "fees": t.fees,
                "taxes": t.taxes,
                "note": t.note,
                "imported": t.import_batch_id is not None or t.external_id is not None,
            }
            for t in rows[:limit]
        ],
    }


def _category_id(db: Session, value: Any) -> int:
    from ..models import Category

    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        cat = db.get(Category, int(value))
    else:
        cat = next((c for c in db.scalars(select(Category)).all() if c.name.lower() == str(value).strip().lower()), None)
    if cat is None:
        raise ToolError(f"Kategorie „{value}“ nicht gefunden – siehe list_categories.")
    return cat.id


def t_list_categories(db: Session, user: User, args: dict) -> Any:
    from ..api.recurring import list_categories

    return list_categories(db)


def t_create_category(db: Session, user: User, args: dict) -> Any:
    from ..api.recurring import CategoryIn, create_category, list_categories

    name = str(args["name"]).strip()
    existing = next((c for c in list_categories(db) if c["name"].lower() == name.lower()), None)
    if existing:
        return {"created": False, "category": existing}
    return {"created": True, "category": create_category(CategoryIn(name=name, kind=args.get("kind", "expense")), db)}


def t_create_category_rule(db: Session, user: User, args: dict) -> Any:
    from ..api.recurring import RuleIn, create_rule

    data = RuleIn(
        pattern=args["pattern"],
        field=args.get("field", "any"),
        direction=args.get("direction", "out"),
        account_id=args.get("account_id"),
        category_id=_category_id(db, args["category"]),
    )
    return create_rule(data, db)


def t_set_recurring_category(db: Session, user: User, args: dict) -> Any:
    from ..api.recurring import RecurringUpdate, update_recurring
    from ..models import RecurringPayment

    value = args["recurring"]
    rows = db.scalars(select(RecurringPayment)).all()
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        hits = [r for r in rows if r.id == int(value)]
    else:
        hits = [r for r in rows if str(value).strip().lower() in r.name.lower()]
    if not hits:
        raise ToolError(f"Kein Vertrag „{value}“ gefunden – siehe get_recurring_payments.")
    if len(hits) > 1:
        raise ToolError("Mehrere Verträge passen: " + ", ".join(f"{r.id} {r.name}" for r in hits) + " – bitte per ID angeben.")
    r = hits[0]
    update_recurring(r.id, RecurringUpdate(name=r.name, interval=r.interval, category_id=_category_id(db, args["category"]), status=r.status, note=r.note), db)
    return {"updated": True, "recurring": r.name, "category": args["category"]}


def t_get_recurring(db: Session, user: User, args: dict) -> Any:
    from ..api.recurring import overview

    data = overview(db)
    keep = ("name", "direction", "interval_label", "category", "amount", "amount_varies", "monthly", "last_date", "next_date", "overdue", "changed", "status", "account")
    return {
        "summary_per_month": data["summary"],
        "by_category_per_month": data["by_category"],
        "items": [{k: i[k] for k in keep} for i in data["items"]],
        "open_suggestions": [{k: s[k] for k in ("name", "direction", "interval_label", "amount", "monthly", "account")} for s in data["suggestions"]],
    }


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


MONEY = {"type": ["number", "string"], "description": "Betrag in Euro, Dezimalpunkt"}
DATE = {"type": "string", "description": "YYYY-MM-DD"}
OWNERS = {
    "type": "array",
    "description": "Eigentümer mit Anteil (Summe 1); Standard: angemeldete Person zu 100 %",
    "items": {"type": "object", "properties": {"person": {"type": ["string", "integer"]}, "share": {"type": ["number", "string"]}}, "required": ["person", "share"]},
}

TOOLS: dict[str, tuple[Callable, dict, bool, str]] = {
    "list_persons": (t_list_persons, _schema({}), False, "Personen im Haushalt."),
    "list_account_kinds": (t_list_account_kinds, _schema({}), False, "Verfügbare Kontoarten und welche Felder (details) sie nutzen."),
    "list_accounts": (t_list_accounts, _schema({"include_closed": {"type": "boolean"}}), False, "Alle Konten und Anlagen mit aktuellem Wert."),
    "get_account": (t_get_account, _schema({"account_id": {"type": "integer"}}, ["account_id"]), False, "Details eines Kontos: Angaben, Bewertungen, letzte Buchungen, Positionen."),
    "get_net_worth": (t_get_net_worth, _schema({"person": {"type": ["string", "integer"]}}), False, "Aktuelles Vermögen, Schulden, Nettovermögen, Aufteilung nach Anlageklasse sowie verfügbar vs. gebunden (mit frei-ab-Datum)."),
    "get_performance": (
        t_get_performance,
        _schema({"account_id": {"type": "integer"}, "person": {"type": ["string", "integer"]}, "period": {"type": "string", "enum": PERIODS}}),
        False,
        "Rendite (TTWROR, IZF, Gewinn) für den Haushalt, eine Person oder ein Konto.",
    ),
    "get_holding_period": (
        t_get_holding_period,
        _schema({"account_id": {"type": "integer"}, "on": DATE}, ["account_id"]),
        False,
        "Haltefrist (§ 23 EStG) für Krypto- und Edelmetall-Konten: je Kaufposten frei ab, steuerfrei verkaufbare Menge, Gewinne nach Jahr.",
    ),
    "list_trades": (
        t_list_trades,
        _schema(
            {
                "account_id": {"type": "integer"},
                "isin": {"type": "string"},
                "type": {"type": "string", "enum": ["buy", "sell", "deliver_in", "deliver_out", "dividend", "interest", "tax", "tax_refund", "fee", "advance_tax", "split"]},
                "from": DATE,
                "to": DATE,
                "limit": {"type": "integer"},
            },
            ["account_id"],
        ),
        False,
        "Wertpapier-Buchungen eines Depots (Käufe, Verkäufe, Einlieferungen, Dividenden …), neueste zuerst; filterbar nach ISIN, Art und Zeitraum.",
    ),
    "list_categories": (t_list_categories, _schema({}), False, "Kategorien für Ausgaben, Einnahmen, Sparen (transfer) und Umbuchungen (internal)."),
    "create_category": (
        t_create_category,
        _schema({"name": {"type": "string"}, "kind": {"type": "string", "enum": ["expense", "income", "transfer", "internal"]}}, ["name"]),
        True,
        "Neue Kategorie anlegen (gibt eine vorhandene gleichnamige zurück).",
    ),
    "create_category_rule": (
        t_create_category_rule,
        _schema(
            {
                "pattern": {"type": "string", "description": "Text, der im Empfänger/Zweck vorkommen muss (Groß-/Kleinschreibung egal)"},
                "category": {"type": ["string", "integer"], "description": "Name oder ID der Kategorie"},
                "field": {"type": "string", "enum": ["any", "counterparty", "purpose"]},
                "direction": {"type": "string", "enum": ["out", "in", "any"]},
                "account_id": {"type": "integer"},
            },
            ["pattern", "category"],
        ),
        True,
        "Regel: Buchungen, deren Empfänger/Zweck den Text enthält, bekommen die Kategorie (gilt auch künftig).",
    ),
    "set_recurring_category": (
        t_set_recurring_category,
        _schema({"recurring": {"type": ["string", "integer"], "description": "Name (Teil) oder ID des Vertrags"}, "category": {"type": ["string", "integer"]}}, ["recurring", "category"]),
        True,
        "Kategorie eines Vertrags/Abos ändern; seine Buchungen ziehen mit.",
    ),
    "get_recurring_payments": (
        t_get_recurring,
        _schema({}),
        False,
        "Verträge, Abos und regelmäßige Einnahmen: Fixkosten je Monat nach Kategorie, nächste Fälligkeit, Preisänderungen, offene Vorschläge.",
    ),
    "create_account": (
        t_create_account,
        _schema(
            {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": list(kinds.KINDS)},
                "institution": {"type": "string"},
                "iban": {"type": "string"},
                "opened_on": DATE,
                "notes": {"type": "string"},
                "details": {"type": "object", "description": "Kontoart-spezifische Felder, siehe list_account_kinds"},
                "owners": OWNERS,
            },
            ["name", "kind"],
        ),
        True,
        "Neues Konto bzw. neue Anlage anlegen.",
    ),
    "update_account": (
        t_update_account,
        _schema(
            {"account_id": {"type": "integer"}, "name": {"type": "string"}, "institution": {"type": "string"}, "opened_on": DATE, "notes": {"type": "string"}, "closed": {"type": "boolean"}, "details": {"type": "object", "description": "wird mit den bestehenden Feldern zusammengeführt"}, "owners": OWNERS},
            ["account_id"],
        ),
        True,
        "Angaben eines Kontos ändern (Kontoart bleibt).",
    ),
    "add_valuation": (
        t_add_valuation,
        _schema({"account_id": {"type": "integer"}, "date": DATE, "value": MONEY, "note": {"type": "string"}}, ["account_id", "date", "value"]),
        True,
        "Wert einer Anlage zu einem Stichtag (Immobilie, Altersvorsorge, Sonstiges). Gleicher Stichtag überschreibt.",
    ),
    "add_balance": (
        t_add_balance,
        _schema({"account_id": {"type": "integer"}, "date": DATE, "amount": MONEY}, ["account_id", "date", "amount"]),
        True,
        "Kontostand zu einem Stichtag (Giro, Tagesgeld, Kreditkarte; bei Krediten die Restschuld negativ).",
    ),
    "add_transaction": (
        t_add_transaction,
        _schema(
            {
                "account_id": {"type": "integer"},
                "date": DATE,
                "amount": MONEY,
                "kind": {"type": "string", "enum": list(kinds.TRANSACTION_KINDS)},
                "counterparty": {"type": "string"},
                "purpose": {"type": "string"},
            },
            ["account_id", "date", "amount"],
        ),
        True,
        "Buchung: Umsatz auf einem Konto, Beitrag zu einer Versicherung (kind contribution), Sondertilgung (prepayment) usw.",
    ),
    "add_trade": (
        t_add_trade,
        _schema(
            {
                "account_id": {"type": "integer"},
                "date": DATE,
                "type": {"type": "string", "enum": list(kinds.TRADE_TYPES)},
                "instrument_id": {"type": "integer"},
                "isin": {"type": "string"},
                "instrument_name": {"type": "string"},
                "instrument_kind": {"type": "string", "enum": list(kinds.INSTRUMENT_KINDS)},
                "quantity": MONEY,
                "price": MONEY,
                "amount": MONEY,
                "fees": MONEY,
                "taxes": MONEY,
                "note": {"type": "string"},
            },
            ["account_id", "date", "type"],
        ),
        True,
        "Depot-Transaktion (Kauf, Verkauf, Dividende …). Wertpapier per instrument_id oder ISIN; unbekannte werden angelegt.",
    ),
}


# German labels for the audit log of writing tools.
TOOL_LABELS = {
    "create_account": "Konto angelegt",
    "update_account": "Konto geändert",
    "add_valuation": "Bewertung eingetragen",
    "add_balance": "Kontostand eingetragen",
    "add_transaction": "Buchung angelegt",
    "add_trade": "Depot-Transaktion angelegt",
    "create_category": "Kategorie angelegt",
    "create_category_rule": "Kategorieregel angelegt",
    "set_recurring_category": "Kategorie eines Vertrags geändert",
}


def _tool_list() -> list[dict]:
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": schema,
            "annotations": {"readOnlyHint": not writes, "destructiveHint": False, "idempotentHint": False},
        }
        for name, (_, schema, writes, desc) in TOOLS.items()
    ]


def _audit(db: Session, user: User, client_id: str | None, name: str, args: dict) -> None:
    client = db.get(OAuthClient, client_id) if client_id else None
    target = ""
    account_id = args.get("account_id")
    if isinstance(account_id, int) or (isinstance(account_id, str) and account_id.isdigit()):
        account = db.get(Account, int(account_id))
        target = f"Konto {account.name}" if account else f"Konto #{account_id}"
    audit.record(db, user_id=user.id, actor=user.name, via="mcp", client=client.name if client else "", action=TOOL_LABELS.get(name, name), target=target, detail=audit.detail(args))
    db.commit()


def _call(db: Session, user: User, name: str, args: dict, client_id: str | None = None) -> dict:
    if name not in TOOLS:
        raise KeyError(name)
    fn, _, writes, _ = TOOLS[name]
    try:
        result = fn(db, user, args or {})
        if writes:
            cache.bump()
            _audit(db, user, client_id, name, args or {})
        return {"content": [{"type": "text", "text": _json(result)}], "isError": False}
    except (ToolError, KeyError, ValueError, ValidationError) as exc:
        db.rollback()
        return {"content": [{"type": "text", "text": f"Fehler: {exc}"}], "isError": True}
    except HTTPException as exc:
        db.rollback()
        return {"content": [{"type": "text", "text": f"Fehler: {exc.detail}"}], "isError": True}


def _handle(db: Session, user: User, msg: dict, client_id: str | None = None) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")
    if mid is None:
        return None  # notification
    params = msg.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list()}
    elif method == "tools/call":
        try:
            result = _call(db, user, params.get("name", ""), params.get("arguments") or {}, client_id)
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unbekanntes Werkzeug: {params.get('name')}"}}
    elif method in ("resources/list", "prompts/list"):
        result = {method.split("/")[0]: []}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Methode nicht unterstützt: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


@router.post("/mcp")
async def mcp_post(request: Request, db: Session = Depends(get_db)) -> Response:
    user, client_id = require_bearer(request, db)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    messages = payload if isinstance(payload, list) else [payload]
    replies = [r for r in (_handle(db, user, m, client_id) for m in messages if isinstance(m, dict)) if r is not None]
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0], headers={"Cache-Control": "no-store"})


@router.get("/mcp")
def mcp_get(request: Request, db: Session = Depends(get_db)) -> Response:
    # No server-initiated stream; still answer 401 first so clients discover OAuth.
    require_bearer(request, db)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
def mcp_delete() -> Response:
    return Response(status_code=200)


__all__ = ["router", "challenge_headers"]
