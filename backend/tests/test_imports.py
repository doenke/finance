import json
from decimal import Decimal as D

import pytest
from sqlalchemy import text

from finanzen.services.backup import export_data, restore_data
from finanzen.services.csvimport import ImportError_, guess_mapping, header_index, parse_bookings, parse_decimal, parse_portfolio_performance, sniff

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}

SPARKASSE = '''"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";"Glaeubiger ID";"Mandatsreferenz";"Kundenreferenz (End-to-End)";"Sammlerreferenz";"Lastschrift Ursprungsbetrag";"Auslagenersatz Ruecklastschrift";"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info"
"DE00123";"03.11.26";"03.11.26";"LASTSCHRIFT";"Strom November";"";"";"";"";"";"";"Stadtwerke";"DE11";"X";"-89,90";"EUR";"Umsatz gebucht"
"DE00123";"01.11.26";"01.11.26";"GUTSCHRIFT";"Gehalt";"";"";"";"";"";"";"Arbeitgeber GmbH";"DE22";"Y";"3.456,78";"EUR";"Umsatz gebucht"
'''

DKB = '''"Girokonto";"DE00 1234"
"Zeitraum:";"01.10.2026 - 31.10.2026"
"Kontostand vom 31.10.2026:";"1.234,56 €"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
"30.10.26";"30.10.26";"Gebucht";"Max";"REWE";"Einkauf";"Ausgang";"DE1";"-45,10";"";"";""
'''

PP = """Datum;Typ;Wert;Buchungswährung;Bruttobetrag;Währung Bruttobetrag;Wechselkurs;Gebühren;Steuern;Stück;ISIN;WKN;Ticker-Symbol;Wertpapiername;Notiz
2024-01-10T00:00;Kauf;-1.001,00;EUR;;;;1,00;;10;IE00B4L5Y983;A0RPWH;EUNL.DE;iShares Core MSCI World;
2024-06-10T00:00;Verkauf;359,00;EUR;;;;1,00;;4;IE00B4L5Y983;A0RPWH;EUNL.DE;iShares Core MSCI World;
2024-07-01T00:00;Dividende;2,70;EUR;;;;;0,50;;IE00B4L5Y983;A0RPWH;EUNL.DE;iShares Core MSCI World;
2024-07-02T00:00;Einlage;500,00;EUR;;;;;;;;;;;
"""


@pytest.mark.parametrize(
    "raw,expected",
    [("-89,90", "-89.90"), ("3.456,78", "3456.78"), ("1,234.50", "1234.50"), ("12.50", "12.50"), ("250.000", "250000"), ("1.234,56 €", "1234.56"), ("45,10-", "-45.10"), ("+5", "5")],
)
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == D(expected)


def test_parse_decimal_invalid():
    with pytest.raises(ImportError_):
        parse_decimal("abc")


def test_sparkasse_and_dkb_detection():
    _, rows = sniff(SPARKASSE)
    m = guess_mapping(rows[0])
    assert rows[0][m["booking_date"]] == "Buchungstag"
    assert rows[0][m["amount"]] == "Betrag"
    assert rows[0][m["counterparty"]] == "Beguenstigter/Zahlungspflichtiger"
    header, parsed = parse_bookings(SPARKASSE, m, 1)
    assert [p.amount for p in parsed] == [D("-89.90"), D("3456.78")]
    assert parsed[0].booking_date.isoformat() == "2026-11-03"
    assert len({p.external_id for p in parsed}) == 2

    dkb_rows = sniff(DKB)[1]
    header, parsed = parse_bookings(DKB, guess_mapping(dkb_rows[header_index(dkb_rows)]), 1)
    assert header[0] == "Buchungsdatum"
    assert parsed[0].amount == D("-45.10")
    assert parsed[0].counterparty in ("REWE", "Max")


def test_portfolio_performance_parse():
    rows = parse_portfolio_performance(PP, 1)
    buy, sell, div, deposit = rows
    assert (buy.type, buy.quantity, buy.amount, buy.fees) == ("buy", D("10"), D("1000.00"), D("1.00"))
    assert (sell.type, sell.amount) == ("sell", D("360.00"))
    assert (div.type, div.amount, div.taxes) == ("dividend", D("3.20"), D("0.50"))
    assert deposit.skipped


def test_booking_import_flow(client):
    login(client)
    giro = client.post("/api/accounts", json={"name": "Giro", "kind": "giro"}, headers=ORIGIN).json()
    body = {"account_id": giro["id"], "text": SPARKASSE, "filename": "umsatz.csv"}
    pre = client.post("/api/import/bookings/preview", json=body, headers=ORIGIN).json()
    assert pre["summary"] == {"new": 2, "duplicate": 0, "error": 0}
    body["mapping"] = pre["mapping"]
    body["profile"] = "Sparkasse"
    res = client.post("/api/import/bookings/commit", json=body, headers=ORIGIN).json()
    assert res["imported"] == 2
    again = client.post("/api/import/bookings/preview", json=body, headers=ORIGIN).json()
    assert again["summary"]["duplicate"] == 2
    assert "Sparkasse" in client.get("/api/import/profiles").json()
    assert D(client.get(f"/api/accounts/{giro['id']}").json()["value"]) == D("3366.88")
    batches = client.get("/api/import/batches").json()
    assert batches[0]["count"] == 2
    assert client.delete(f"/api/import/batches/{batches[0]['id']}", headers=ORIGIN).status_code == 204
    assert D(client.get(f"/api/accounts/{giro['id']}").json()["value"]) == 0
    csv_text = client.get("/api/export/transactions.csv").text
    assert csv_text.startswith("﻿Konto;")


def test_portfolio_performance_import(client):
    login(client)
    depot = client.post("/api/accounts", json={"name": "Depot", "kind": "depot"}, headers=ORIGIN).json()
    body = {"account_id": depot["id"], "text": PP}
    pre = client.post("/api/import/portfolio-performance/preview", json=body, headers=ORIGIN).json()
    assert pre["summary"] == {"new": 3, "duplicate": 0, "error": 0, "skipped": 1}
    res = client.post("/api/import/portfolio-performance/commit", json=body, headers=ORIGIN).json()
    assert res["imported"] == 3 and res["instruments"] == 1
    pos = client.get(f"/api/accounts/{depot['id']}/positions").json()[0]
    assert D(pos["quantity"]) == 6
    assert pos["instrument"]["price_symbol"] == "EUNL.DE"
    assert D(pos["income"]) == D("3.20")
    assert client.post("/api/import/portfolio-performance/preview", json=body, headers=ORIGIN).json()["summary"]["duplicate"] == 3


def test_export_backup_restore_roundtrip(client, tmp_path):
    login(client, "Anna")
    acc = client.post("/api/accounts", json={"name": "Wohnung", "kind": "immobilie", "details": {"purchase_price": "1"}}, headers=ORIGIN).json()
    client.post(f"/api/accounts/{acc['id']}/valuations", json={"date": "2025-01-01", "value": "123456.78"}, headers=ORIGIN)
    giro = client.post("/api/accounts", json={"name": "Verrechnung", "kind": "verrechnung"}, headers=ORIGIN).json()
    client.post("/api/accounts", json={"name": "Depot", "kind": "depot", "settlement_account_id": giro["id"]}, headers=ORIGIN)
    exported = client.get("/api/export/json").json()
    assert exported["format"] == "finanzen-backup"
    assert exported["tables"]["valuations"][0]["value"] == {"$dec": "123456.78"}

    # Backups need admin rights
    assert client.get("/api/admin/backups").status_code == 200
    made = client.post("/api/admin/backups", headers=ORIGIN).json()
    assert made["file"].endswith(".json.gz")
    files = client.get("/api/admin/backups").json()["files"]
    assert files[0]["name"] == made["file"]
    assert client.get(f"/api/admin/backups/{made['file']}").status_code == 200
    assert client.get("/api/admin/backups/..%2Fetc%2Fpasswd").status_code == 404

    sm = client.app.state.sessionmaker
    with sm() as db:
        data = export_data(db)
        with pytest.raises(ValueError):
            restore_data(db, data)  # not empty
        tables = [t for t in data["tables"]]
    # wipe all data, keep schema, then restore
    with sm() as db:
        db.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
        db.commit()
        counts = restore_data(db, json.loads(json.dumps(data)))
        assert counts["accounts"] == 3
    accounts = client.get("/api/accounts").json()
    depot = next(a for a in accounts if a["kind"] == "depot")
    assert depot["settlement_account_id"] == giro["id"]
    assert D(next(a for a in accounts if a["kind"] == "immobilie")["value"]) == D("123456.78")
    # new rows still get fresh ids
    new = client.post("/api/accounts", json={"name": "Neu", "kind": "giro"}, headers=ORIGIN).json()
    assert new["id"] > 3


def test_backup_requires_admin(client):
    login(client, "Ben", admin=False)
    assert client.get("/api/admin/backups").status_code == 403
