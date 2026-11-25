from datetime import date
from decimal import Decimal as D

from finanzen.models import Account, Person
from finanzen.services.retirement import Params, income_tax, projection, taxable_share_statutory

from .conftest import login
from .test_mcp import connect, tool

ORIGIN = {"Origin": "https://finanzen.example.org"}


def test_tax_helpers():
    assert income_tax(12000) == 0
    assert 2600 < income_tax(24000) < 2700  # ~2.66k at 24k (2025)
    assert taxable_share_statutory(2026) == 0.84 and taxable_share_statutory(2060) == 1.0


def test_projection(client):
    login(client, "Sönke Jacobs")
    today = date(2026, 11, 25)
    with client.app.state.sessionmaker() as db:
        person = db.query(Person).first()
        pid = person.id

        def acc(name, kind, details=None):
            from finanzen.models import AccountOwner

            a = Account(name=name, kind=kind, asset_class="pension" if kind == "altersvorsorge" else "cash", details=details or {})
            db.add(a)
            db.flush()
            db.add(AccountOwner(account_id=a.id, person_id=pid, share=D(1)))
            return a

        acc("DRV", "altersvorsorge", {"product": "gesetzlich", "expected_pension": "2000", "payout_start": "2046-10-01"})
        acc("Privatrente", "altersvorsorge", {"product": "rente", "expected_pension": "300", "payout_start": "2046-10-01"})
        tg = acc("Tagesgeld", "tagesgeld")
        from finanzen.models import BalanceSnapshot

        db.add(BalanceSnapshot(account_id=tg.id, date=today, amount=D("100000")))
        db.commit()
        data = projection(db, pid, Params(savings=0, inflation=0.02, years=25), today=today)
    assert data["retire_on"] == date(2046, 10, 1)  # from the statutory pension
    drv, private = data["pensions"]
    assert drv["product"] == "gesetzlich" and drv["monthly"] == 2000  # already today's money
    assert private["monthly"] < 300 * 0.7  # deflated over ~20 years
    mid = next(s for s in data["scenarios"] if s["key"] == "mittel")
    real = (1.05 / 1.02) ** (1 / 12) - 1
    months = (2046 - 2026) * 12 + (10 - 11)
    assert abs(mid["capital"] - 100000 * (1 + real) ** months) < 2
    assert mid["withdrawal"] > 0 and mid["net"] < mid["gross"] and mid["health"] > 0
    low = next(s for s in data["scenarios"] if s["key"] == "vorsichtig")
    assert low["capital"] < mid["capital"]
    assert data["scenarios"][0]["series"][0]["value"] == 100000

    # the API picks the logged-in user's person and validates input
    res = client.get("/api/retirement", params={"savings": 500})
    assert res.status_code == 200 and res.json()["inputs"]["savings"] == 500
    assert client.get("/api/retirement", params={"inflation": 0.5}).status_code == 422


def test_mcp_pension_statement(client):
    tokens, _ = connect(client)
    access = tokens["access_token"]
    err, out = tool(client, access, "add_pension_statement", {"person": "Anna", "date": "2025-07-01", "projected": "1800.50", "current": "900", "payout_start": "2046-10-01"})
    assert not err, out
    aid = out["account_id"]
    err, out = tool(client, access, "add_pension_statement", {"person": "Anna", "date": "2026-07-01", "projected": "1890.10", "current": "980"})
    assert out["account_id"] == aid and out["statements"] == 2
    assert out["current"]["expected_pension"] == "1890.10" and out["current"]["payout_start"] == "2046-10-01"
    # an older statement added later keeps the newest figures
    err, out = tool(client, access, "add_pension_statement", {"account_id": aid, "date": "2024-07-01", "projected": "1700"})
    assert out["statements"] == 3 and out["current"]["expected_pension"] == "1890.10"
    err, proj = tool(client, access, "get_retirement_projection", {"person": "Anna"})
    assert not err, proj
    assert proj["pensions"][0]["monthly"] == 1890.1 and "series" not in proj["scenarios"][0]
