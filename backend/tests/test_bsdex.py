from decimal import Decimal as D
from pathlib import Path

from finanzen.services.bsdex import is_bsdex, parse_bsdex

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}
CSV = (Path(__file__).parent / "fixtures_bsdex.csv").read_text(encoding="utf-8")


def test_parse_bsdex():
    assert is_bsdex(CSV)
    rows = parse_bsdex(CSV, 1)
    buys = [r for r in rows if r.kind == "buy"]
    assert len(buys) == 3
    first = buys[0]
    assert first.quantity == D("0.10022757")
    assert first.amount == D("9965.12")
    assert first.price == D("99424.88")
    assert first.fee == D("34.88")
    assert first.date.isoformat() == "2025-08-04"
    assert sum(1 for r in rows if r.kind == "deposit") == 3
    rejected = [r for r in rows if r.skipped]
    assert len(rejected) == 1 and "Abgelehnt" not in rejected[0].skipped and "nicht ausgeführt" in rejected[0].skipped
    assert not any(r.error for r in rows)


def test_bsdex_import(client):
    login(client)
    depot = client.post("/api/accounts", json={"name": "BSDEX", "kind": "krypto", "institution": "BSDEX"}, headers=ORIGIN).json()
    body = {"account_id": depot["id"], "text": CSV, "filename": "Transactions.csv"}
    pre = client.post("/api/import/bsdex/preview", json=body, headers=ORIGIN).json()
    assert pre["summary"] == {"new": 6, "duplicate": 0, "error": 0, "skipped": 1}
    assert pre["settlement"] is None
    res = client.post("/api/import/bsdex/commit", json=body, headers=ORIGIN).json()
    assert res["trades"] == 3 and res["cash"] == 6
    pos = client.get(f"/api/accounts/{depot['id']}/positions").json()[0]
    assert D(pos["quantity"]) == D("0.41840447")
    assert pos["instrument"]["price_symbol"] == "BTC-EUR"
    assert D(pos["cost"]) == D("35000.00") - D("0.01")  # 3 orders incl. fees
    euro = client.get(f"/api/accounts/{res['settlement_id']}").json()
    assert euro["kind"] == "verrechnung"
    assert D(euro["value"]) == D("0.01")  # 35,000 paid in, 34,999.99 spent
    again = client.post("/api/import/bsdex/preview", json=body, headers=ORIGIN).json()
    assert again["summary"]["duplicate"] == 6 and again["settlement"]["id"] == res["settlement_id"]
    # undo removes trades and euro bookings
    client.delete(f"/api/import/batches/{res['batch_id']}", headers=ORIGIN)
    assert client.get(f"/api/accounts/{depot['id']}/positions").json() == []
    assert D(client.get(f"/api/accounts/{res['settlement_id']}").json()["value"]) == 0
