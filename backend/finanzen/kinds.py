"""Account kinds, asset classes and transaction types (single source of truth for API and UI)."""

from dataclasses import dataclass

# How the value of an account is determined.
CASH = "cash"  # balance snapshots + transactions
HOLDINGS = "holdings"  # positions (trades) x prices
VALUATION = "valuation"  # manual valuations at dates
DEPOSIT = "deposit"  # fixed-term deposit, accrues interest
LOAN = "loan"  # outstanding debt from the amortization schedule (negative)


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    mode: str
    asset_class: str
    liability: bool = False
    bound: bool = False  # default for "available vs. bound": money you cannot use at short notice


KINDS: dict[str, Kind] = {
    k.key: k
    for k in [
        Kind("giro", "Girokonto", CASH, "cash"),
        Kind("tagesgeld", "Tagesgeld", CASH, "cash"),
        Kind("verrechnung", "Verrechnungskonto", CASH, "cash"),
        Kind("festgeld", "Festgeld", DEPOSIT, "cash", bound=True),
        Kind("kreditkarte", "Kreditkarte", CASH, "liabilities", liability=True),
        Kind("depot", "Depot", HOLDINGS, "securities"),
        Kind("krypto", "Krypto", HOLDINGS, "crypto"),
        Kind("stak", "STAK-Anteile", HOLDINGS, "participations", bound=True),
        Kind("edelmetall", "Edelmetalle", HOLDINGS, "metals"),
        Kind("immobilie", "Immobilie", VALUATION, "real_estate", bound=True),
        Kind("altersvorsorge", "Altersvorsorge & Versicherung", VALUATION, "pension", bound=True),
        Kind("sonstiges", "Sonstige Anlage", VALUATION, "other", bound=True),
        Kind("kredit", "Kredit", LOAN, "liabilities", liability=True),
    ]
}

ASSET_CLASSES: dict[str, str] = {
    "cash": "Bargeld & Konten",
    "securities": "Wertpapiere",
    "crypto": "Krypto",
    "participations": "Beteiligungen",
    "metals": "Edelmetalle",
    "real_estate": "Immobilien",
    "pension": "Altersvorsorge",
    "other": "Sonstiges",
    "liabilities": "Verbindlichkeiten",
}

TRANSACTION_KINDS: dict[str, str] = {
    "other": "Sonstiges",
    "deposit": "Einzahlung",
    "withdrawal": "Auszahlung",
    "transfer": "Umbuchung",
    "interest": "Zinsen",
    "fee": "Gebühr",
    "tax": "Steuer",
    "income": "Ertrag",
    "contribution": "Beitrag",
    "prepayment": "Sondertilgung",
    "installment": "Rate",
}

# Portfolio transaction types. quantity_sign: effect on the position; cash: effect on value leaving/entering.
TRADE_TYPES: dict[str, str] = {
    "buy": "Kauf",
    "sell": "Verkauf",
    "deliver_in": "Einlieferung",
    "deliver_out": "Auslieferung",
    "dividend": "Dividende/Ausschüttung",
    "interest": "Zinsen",
    "tax": "Steuer",
    "tax_refund": "Steuererstattung",
    "fee": "Gebühr",
    "advance_tax": "Vorabpauschale",
    "split": "Split",
}

QUANTITY_TYPES = {"buy", "sell", "deliver_in", "deliver_out", "split"}
INSTRUMENT_TYPES = {"buy", "sell", "deliver_in", "deliver_out", "dividend", "split", "advance_tax"}

INSTRUMENT_KINDS: dict[str, str] = {
    "stock": "Aktie",
    "etf": "ETF",
    "fund": "Fonds",
    "bond": "Anleihe",
    "certificate": "Zertifikat",
    "crypto": "Kryptowährung",
    "metal": "Edelmetall",
    "stak": "STAK-Zertifikat",
    "other": "Sonstiges",
}

UNITS: dict[str, str] = {"piece": "Stück", "g": "Gramm", "oz": "Unze"}
