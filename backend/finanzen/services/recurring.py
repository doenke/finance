"""Recurring payments: detection from transactions, matching rules, category suggestions and the overview."""

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import kinds
from ..models import Account, Category, RecurringPayment, Transaction

ZERO = Decimal("0")
LOOKBACK_DAYS = 730

# base length in days, tolerance per period, months per period (None = weekly)
INTERVALS: dict[str, tuple[float, float, int | None]] = {
    "weekly": (7.0, 2.0, None),
    "monthly": (30.44, 6.0, 1),
    "quarterly": (91.3, 12.0, 3),
    "halfyearly": (182.6, 20.0, 6),
    "yearly": (365.25, 25.0, 12),
}
INTERVAL_LABELS = {"weekly": "wöchentlich", "monthly": "monatlich", "quarterly": "vierteljährlich", "halfyearly": "halbjährlich", "yearly": "jährlich"}

# Payment processors: the merchant is in the purpose, not in the counterparty.
PROCESSORS = ("paypal", "klarna", "sumup", "stripe", "adyen", "amazon payments", "mollie", "unzer", "computop", "wirecard", "payone")
NOISE = {
    "sepa", "lastschrift", "basislastschrift", "folgelastschrift", "erstlastschrift", "dauerauftrag", "gutschrift", "überweisung",
    "ueberweisung", "kartenzahlung", "karte", "einzug", "mandat", "mandatsref", "ref", "end", "eref", "kref", "svwz", "abwa", "cred",
    "gmbh", "mbh", "co", "kg", "ag", "se", "ev", "e.v", "eg", "ug", "ltd", "inc", "bv", "b.v", "sarl", "s.a", "und", "the", "for", "von",
    "der", "die", "das", "ihr", "ihre", "einkauf", "bei", "zahlung", "payment", "vielen", "dank", "kundennr", "kunde", "rechnung", "nr",
    "vertrag", "vertragsnr", "monat", "beitrag", "lastschr", "incoming", "outgoing", "transfer", "from", "to", "fuer", "für", "mit",
}
IBAN_RE = re.compile(r"\b[a-z]{2}\d{2}(?:\s?[a-z0-9]){10,30}\b", re.I)
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def _words(text: str, min_len: int = 2) -> list[str]:
    text = UUID_RE.sub(" ", IBAN_RE.sub(" ", text.lower()))
    tokens = re.split(r"[^a-zäöüß&+.]+", text)
    out = []
    for t in tokens:
        t = t.strip(".")
        if len(t) <= min_len - 1 or t in NOISE or any(ch.isdigit() for ch in t):
            continue
        out.append(t)
    return out


def match_key(counterparty: str, purpose: str) -> str:
    cp = " ".join(_words(counterparty or "")[:5])
    if cp and not any(p in cp for p in PROCESSORS):
        return cp[:200]
    words = _words(purpose or "", min_len=3)[:4]
    if cp:
        return f"{cp}|{' '.join(words)}"[:200]
    return ("zweck:" + " ".join(words))[:200] if words else ""


LEGAL_FORMS = re.compile(r"(?<!\w)(GmbH|mbH|AG|KG|SE|e\.\s?V\.?|eG|UG|Ltd\.?|Inc\.?|B\.\s?V\.?|S\.\s?A\.?|S\.a\.r\.l\.?|& Co\.?)(?!\w)", re.I)


def suggest_name(counterparty: str, purpose: str, key: str) -> str:
    cp = (counterparty or "").strip()
    if cp and not any(p in cp.lower() for p in PROCESSORS):
        cleaned = re.sub(r"\s{2,}", " ", LEGAL_FORMS.sub("", cp)).strip(" ,.-")
        return cleaned[:120] or cp[:120]
    words: list[str] = []
    for w in key.split("|", 1)[-1].removeprefix("zweck:").split():
        if w not in words:
            words.append(w)
    return " ".join(w.capitalize() for w in words[:3])[:120] or "Zahlung"


# --- category suggestions --------------------------------------------------------------------------

RULES: list[tuple[str, str, tuple[str, ...]]] = [
    # (category name, direction or "", keywords)
    ("Sparen & Umbuchungen", "", ("sparplan", "trade republic", "scalable", "bauspar", "vermögenswirksam", "vermoegenswirksam", "vwl", "umbuchung", "übertrag", "uebertrag", "depot")),
    ("Steuern & Gebühren", "out", ("kontoführ", "kontofuehr", "finanzamt", "kfz-steuer", "steuer", "gebühr", "gebuehr", "rundfunk", "beitragsservice")),
    ("Gehalt & Lohn", "in", ("gehalt", "lohn", "bezüge", "bezuege", "salary", "besoldung")),
    ("Kindergeld & Zuschüsse", "in", ("kindergeld", "familienkasse", "elterngeld", "zuschuss")),
    ("Zinsen & Dividenden", "in", ("zins", "interest", "dividende", "ausschüttung", "ausschuettung", "ertrag")),
    ("Mieteinnahmen", "in", ("miete",)),
    ("Kredit & Finanzierung", "out", ("darlehen", "kredit", "tilgung", "dsl bank", "finanzierung", "annuität")),
    ("Wohnen & Nebenkosten", "out", ("miete", "hausgeld", "wohnungsbau", "nebenkosten", "hausverwaltung", "grundbesitz", "müll", "abfall")),
    ("Energie & Wasser", "out", ("stadtwerke", "strom", "energie", "e.on", "eon", "vattenfall", "enbw", "rwe", "stawag", "wasser", "entega", "naturstrom", "lichtblick", "polarstern", "tibber", "octopus", "gasversorg")),
    ("Versicherungen", "out", ("versicherung", "allianz", "hdi", "huk", "generali", "ergo", "axa", "devk", "signal iduna", "debeka", "provinzial", "r+v", "gothaer", "zurich", "lvm", "wgv", "barmenia", "continentale", "nürnberger", "alte leipziger", "württembergische", "haftpflicht", "hanse merkur", "hansemerkur", "cosmos")),
    ("Telefon & Internet", "out", ("telekom", "vodafone", "telefonica", "o2", "1&1", "congstar", "netcologne", "unitymedia", "mobilfunk", "fraenk", "drillisch", "netaachen", "glasfaser", "internet")),
    ("Abos & Medien", "out", ("netflix", "spotify", "disney", "prime", "apple.com", "itunes", "google", "youtube", "dazn", "sky", "audible", "zeitung", "spiegel", "zeit verlag", "microsoft", "adobe", "dropbox", "icloud", "openai", "anthropic", "github", "patreon", "abo", "storytel", "kindle")),
    ("Mobilität", "out", ("deutschlandticket", "db vertrieb", "bahn", "aseag", "kvb", "tankstelle", "aral", "shell", "esso", "leasing", "adac", "parken", "sixt", "share now", "miles")),
    ("Gesundheit & Fitness", "out", ("fitness", "mcfit", "urban sports", "gym", "apotheke", "krankenkasse", "zahnarzt", "physio", "wellpass", "egym")),
    ("Kinder & Familie", "out", ("kita", "schule", "kindergarten", "musikschule", "ogs", "betreuung", "taschengeld")),
    ("Vereine & Spenden", "out", ("verein", "e.v.", "spende", "unicef", "greenpeace", "mitglied", "gewerkschaft", "ver.di", "wikimedia")),
]


def suggest_category(db: Session, counterparty: str, purpose: str, direction: str, own_ibans: set[str]) -> int | None:
    text = f"{counterparty} {purpose}".lower()
    compact = re.sub(r"\s", "", text).upper()
    names = {c.name: c.id for c in db.scalars(select(Category)).all()}
    if any(iban in compact for iban in own_ibans):
        return names.get("Sparen & Umbuchungen")
    for name, dirn, words in RULES:
        if dirn and dirn != direction:
            continue
        if any(re.search(rf"(?<![a-zäöü]){re.escape(w)}", text) for w in words):
            return names.get(name)
    return names.get("Sonstige Einnahmen" if direction == "in" else "Sonstige Ausgaben")


# --- detection -------------------------------------------------------------------------------------


@dataclass
class Tx:
    id: int
    account_id: int
    date: date
    amount: Decimal  # signed
    counterparty: str
    purpose: str
    key: str
    category_id: int | None = None

    @property
    def direction(self) -> str:
        return "in" if self.amount > 0 else "out"


@dataclass
class Candidate:
    key: str
    direction: str
    interval: str
    txs: list[Tx]
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    name: str = ""
    category_id: int | None = None
    extra: dict = field(default_factory=dict)


def load_transactions(db: Session, since: date) -> list[Tx]:
    cash_kinds = [k for k, v in kinds.KINDS.items() if v.mode == kinds.CASH]
    rows = db.execute(
        select(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.kind.in_(cash_kinds), Transaction.booking_date >= since, Transaction.amount != 0)
        .order_by(Transaction.booking_date, Transaction.id)
    ).scalars()
    out = []
    for t in rows:
        key = match_key(t.counterparty or "", t.purpose or "")
        if key:
            out.append(Tx(t.id, t.account_id, t.booking_date, t.amount, t.counterparty or "", t.purpose or "", key, t.category_id))
    return out


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def next_date(last: date, interval: str) -> date:
    months = INTERVALS[interval][2]
    return last + timedelta(days=7) if months is None else _add_months(last, months)


def classify_interval(dates: list[date]) -> str | None:
    """Finds the interval that fits the gaps between payments, tolerating an occasional missing payment."""
    if len(dates) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    best: tuple[int, str] | None = None
    for name, (base, tol, _) in INTERVALS.items():
        single = sum(1 for g in gaps if abs(g - base) <= tol)
        double = sum(1 for g in gaps if abs(g - 2 * base) <= tol * 1.5)
        if single + double < len(gaps) or single == 0:
            continue
        need_occurrences = 2 if name in ("yearly", "halfyearly") else 3
        if len(dates) < need_occurrences or single < max(1, round(0.6 * len(gaps))):
            continue
        if best is None or single > best[0]:
            best = (single, name)
    return best[1] if best else None


def _clusters(txs: list[Tx]) -> list[list[Tx]]:
    ordered = sorted(txs, key=lambda t: abs(t.amount))
    groups: list[list[Tx]] = []
    for t in ordered:
        a = abs(t.amount)
        if groups:
            ref = abs(groups[-1][-1].amount)
            if a - ref <= max(Decimal("2"), ref * Decimal("0.15")):
                groups[-1].append(t)
                continue
        groups.append([t])
    return [sorted(g, key=lambda t: t.date) for g in groups]


def _is_active(last: date, interval: str, today: date) -> bool:
    base, tol, _ = INTERVALS[interval]
    return (today - last).days <= 2 * base + tol


def detect(txs: list[Tx], today: date) -> list[Candidate]:
    groups: dict[tuple[str, str], list[Tx]] = defaultdict(list)
    for t in txs:
        groups[(t.key, t.direction)].append(t)
    result: list[Candidate] = []
    for (key, direction), items in groups.items():
        if len(items) < 2:
            continue
        dates = [t.date for t in items]
        interval = classify_interval(dates) if len(set(dates)) == len(dates) else None
        if interval:
            if _is_active(dates[-1], interval, today):
                result.append(Candidate(key, direction, interval, items))
            continue
        for cluster in _clusters(items):
            cd = [t.date for t in cluster]
            if len(set(cd)) != len(cd):
                continue
            interval = classify_interval(cd)
            if interval and _is_active(cd[-1], interval, today):
                lo = min(abs(t.amount) for t in cluster)
                hi = max(abs(t.amount) for t in cluster)
                result.append(Candidate(key, direction, interval, cluster, (lo * Decimal("0.8")).quantize(Decimal("0.01")), (hi * Decimal("1.25")).quantize(Decimal("0.01"))))
    return result


# --- matching stored rules -------------------------------------------------------------------------


def matches(rule: RecurringPayment, t: Tx) -> bool:
    if rule.match_key != t.key or rule.direction != t.direction:
        return False
    a = abs(t.amount)
    if rule.amount_min is not None and a < rule.amount_min:
        return False
    return not (rule.amount_max is not None and a > rule.amount_max)


def rule_covers(rule: RecurringPayment, c: Candidate) -> bool:
    if rule.match_key != c.key or rule.direction != c.direction:
        return False
    if rule.amount_min is None or c.amount_min is None:
        return True
    return not (c.amount_max < rule.amount_min or c.amount_min > rule.amount_max)


def own_ibans(db: Session) -> set[str]:
    return {re.sub(r"\s", "", a.iban).upper() for a in db.scalars(select(Account)).all() if a.iban}


def monthly_factor(interval: str) -> Decimal:
    return Decimal(str(round(30.44 / INTERVALS[interval][0], 6)))


def price_change(txs: list[Tx]) -> dict | None:
    """A stable amount that changed with the latest payment (e.g. a price increase)."""
    if len(txs) < 3:
        return None
    before = {abs(t.amount) for t in txs[-3:-1]}
    prev, cur = abs(txs[-2].amount), abs(txs[-1].amount)
    if len(before) == 1 and prev and abs(cur - prev) / prev > Decimal("0.01"):
        return {"from": prev, "to": cur, "date": txs[-1].date}
    return None


def typical_amount(txs: list[Tx]) -> tuple[Decimal, bool]:
    amounts = [abs(t.amount) for t in txs]
    if price_change(txs):
        return amounts[-1], False
    recent = amounts[-3:]
    varies = (max(amounts) - min(amounts)) > max(Decimal("1"), statistics.median(amounts) * Decimal("0.05"))
    value = recent[-1] if not varies else sum(recent, ZERO) / len(recent)
    return value.quantize(Decimal("0.01")), varies


def describe(txs: list[Tx], interval: str, today: date) -> dict:
    txs = sorted(txs, key=lambda t: t.date)
    amount, varies = typical_amount(txs) if txs else (ZERO, False)
    last = txs[-1] if txs else None
    nxt = next_date(last.date, interval) if last else None
    tol = INTERVALS[interval][1]
    return {
        "amount": amount,
        "amount_varies": varies,
        "monthly": (amount * monthly_factor(interval)).quantize(Decimal("0.01")),
        "yearly": (amount * monthly_factor(interval) * 12).quantize(Decimal("0.01")),
        "count": len(txs),
        "first_date": txs[0].date if txs else None,
        "last_date": last.date if last else None,
        "last_amount": abs(last.amount) if last else None,
        "next_date": nxt,
        "overdue": bool(nxt and (today - nxt).days > max(5, tol)),
        "changed": price_change(txs),
        "account_id": last.account_id if last else None,
    }
