"""Small, tolerant CAMT.052/053 reader for bank statements fetched via FinTS (HKCAZ).

python-fints has its own parser, but it fails on repeated empty elements (TypeError on `None += str`),
which some Sparkassen send. This one reads only what we need and returns dicts shaped like the
transaction data of python-fints (date = booking date, entry_date = value date, amount, names, purpose).
"""

from datetime import date
from decimal import Decimal

from lxml import etree


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _date(node, path: str) -> date | None:
    raw = _text(node, path + "/{*}Dt") or _text(node, path + "/{*}DtTm")[:10]
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def parse_camt(xml: bytes | str, include_pending: bool = False) -> list[dict]:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml, parser)
    out = []
    for ntry in root.iter("{*}Ntry"):
        status = _text(ntry, "{*}Sts/{*}Cd") or _text(ntry, "{*}Sts")
        if status.upper() in ("PDNG", "INFO") and not include_pending:
            continue
        raw_amount = _text(ntry, "{*}Amt")
        if not raw_amount:
            continue
        amount = Decimal(raw_amount)
        credit = _text(ntry, "{*}CdtDbtInd").upper() == "CRDT"
        if not credit:
            amount = -amount
        booking = _date(ntry, "{*}BookgDt")
        value = _date(ntry, "{*}ValDt") or booking
        purpose = " ".join(t for t in ((e.text or "").strip() for e in ntry.iter("{*}Ustrd")) if t)
        side, other = ("Dbtr", "DbtrAcct") if credit else ("Cdtr", "CdtrAcct")
        parties = ntry.find(".//{*}RltdPties")
        name = iban = ""
        if parties is not None:
            name = _text(parties, f"{{*}}{side}/{{*}}Nm") or _text(parties, f"{{*}}{side}/{{*}}Pty/{{*}}Nm")
            iban = _text(parties, f"{{*}}{other}/{{*}}Id/{{*}}IBAN")
        e2e = _text(ntry, ".//{*}Refs/{*}EndToEndId")
        out.append(
            {
                "date": booking or value,
                "entry_date": value,
                "amount": amount,
                "applicant_name": name,
                "applicant_iban": iban,
                "purpose": purpose,
                "posting_text": _text(ntry, "{*}AddtlNtryInf"),
                "end_to_end_reference": "" if e2e.upper() == "NOTPROVIDED" else e2e,
            }
        )
    return out
