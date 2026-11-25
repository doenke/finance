import random
from datetime import date, timedelta
from decimal import Decimal as D

from finanzen.api.recurring import overview
from finanzen.models import Account, Category, Transaction
from finanzen.services import recurring as rec

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}
TODAY = date(2026, 11, 24)


def months_back(n: int, day: int) -> list[date]:
    return [rec._add_months(date(2026, 11, day), -i) for i in range(n)][::-1]


def seed(client) -> dict[str, int]:
    rnd = random.Random(7)
    with client.app.state.sessionmaker() as db:
        giro = Account(name="Giro", kind="giro", asset_class="cash", iban="DE00 1111 2222 3333 4444 55", details={})
        tr = Account(name="Trade Republic", kind="verrechnung", asset_class="cash", iban="DE00999988887777666655", details={})
        db.add_all([giro, tr])
        db.flush()

        def tx(acc, d, amount, cp="", purpose=""):
            db.add(Transaction(account_id=acc.id, booking_date=d, amount=D(str(amount)), counterparty=cp, purpose=purpose))

        # direct debit with a price increase in the last month
        for i, d in enumerate(months_back(10, 15)):
            tx(giro, d, -13.99 if i < 9 else -17.99, "Netflix International B.V.", f"Netflix Mitgliedschaft {d:%m/%Y} Mandat NFX{1000 + i}")
        # two subscriptions over PayPal
        for i, d in enumerate(months_back(8, 3)):
            tx(giro, d, -10.99, "PayPal Europe S.a.r.l. et Cie S.C.A", f"PP.{4000 + i}.PP . Spotify AB, Ihr Einkauf bei Spotify AB")
            tx(giro, d + timedelta(days=1), -8.99, "PayPal Europe S.a.r.l. et Cie S.C.A", f"PP.{5000 + i}.PP . Disney Plus, Ihr Einkauf bei Disney Plus")
        # salary around the end of the month
        for d in months_back(12, 28):
            tx(giro, d + timedelta(days=rnd.randint(-2, 1)), 3500 + rnd.randint(0, 40), "Slimstock GmbH", f"Gehalt {d:%m/%Y}")
        # loan installment and yearly car insurance
        for d in months_back(12, 30 if True else 1):
            tx(giro, d, -890.12, "DSL Bank", "Darlehen 123456789 Rate")
        for d in (date(2024, 12, 1), date(2025, 12, 1)):
            tx(giro, d, -412.50, "HUK-COBURG", "Kfz-Versicherung 2026")
        # monthly savings to own TR account (recognized by the IBAN)
        for d in months_back(6, 2):
            tx(giro, d, -500, "Sönke Jacobs", "Sparrate DE00999988887777666655")
        # TR interest: varying amounts, no counterparty, a UUID in every purpose
        for i, d in enumerate(months_back(6, 1)):
            tx(tr, d, [0.01, 0.02, 10.18, 58.60, 63.83, 61.2][i], "", f"Interest payment for payout collection 019f1c06-ea68-79d7-a8b4-{i:012d}")
        # noise: groceries at random days, an ended gym contract
        for k in range(40):
            tx(giro, TODAY - timedelta(days=rnd.randint(1, 300)), -rnd.randint(5, 120), "REWE Markt", "Kartenzahlung")
        for d in (date(2025, 1, 5), date(2025, 2, 5), date(2025, 3, 5), date(2025, 4, 5)):
            tx(giro, d, -29.90, "McFit GmbH", "Mitgliedsbeitrag")
        db.commit()
        return {"giro": giro.id, "tr": tr.id}


def test_keys_and_intervals():
    assert rec.match_key("Netflix International B.V.", "x") == "netflix international"
    assert rec.match_key("PayPal Europe S.a.r.l. et Cie S.C.A", "PP.4000.PP . Spotify AB, Ihr Einkauf bei Spotify AB") == "paypal europe s.a.r.l et cie|spotify spotify"
    assert rec.match_key("", "Interest payment for payout collection 019f1c06-ea68-79d7-a8b4-000000000001") == "zweck:interest payout collection"
    assert rec.classify_interval(months_back(4, 15)) == "monthly"
    assert rec.classify_interval([date(2025, 1, 1), date(2025, 2, 1), date(2025, 4, 2), date(2025, 5, 1)]) == "monthly"  # one missing month
    assert rec.classify_interval([date(2024, 12, 1), date(2025, 12, 1)]) == "yearly"
    assert rec.classify_interval([date(2025, 1, 1), date(2025, 1, 20), date(2025, 3, 2)]) is None


def test_detection_suggestions_and_overview(client):
    login(client)
    ids = seed(client)
    with client.app.state.sessionmaker() as db:
        data = overview(db, TODAY)
        cats = {c.id: c.name for c in db.query(Category).all()}
    sugg = {s["name"]: s for s in data["suggestions"]}
    assert set(sugg) == {"Netflix International", "Spotify", "Disney Plus", "Slimstock", "DSL Bank", "HUK-COBURG", "Sönke Jacobs", "Interest Payout Collection"}, set(sugg)
    assert sugg["Netflix International"]["interval"] == "monthly" and sugg["Netflix International"]["changed"]["to"] == D("17.99")
    assert sugg["Netflix International"]["amount"] == D("17.99")
    assert sugg["HUK-COBURG"]["interval"] == "yearly" and sugg["HUK-COBURG"]["next_date"] == date(2026, 12, 1)
    assert sugg["Interest Payout Collection"]["amount_varies"] is True and sugg["Interest Payout Collection"]["direction"] == "in"
    expect = {
        "Netflix International": "Abos & Medien",
        "Spotify": "Abos & Medien",
        "Slimstock": "Gehalt & Lohn",
        "DSL Bank": "Kredit & Finanzierung",
        "HUK-COBURG": "Versicherungen",
        "Sönke Jacobs": "Sparen & Umbuchungen",
        "Interest Payout Collection": "Zinsen & Dividenden",
    }
    for name, cat in expect.items():
        assert cats[sugg[name]["category_id"]] == cat, name
    assert not data["items"] and data["summary"]["costs"] == 0

    # accept all but Disney, which is ignored
    for s in data["suggestions"]:
        body = {k: s[k] for k in ("match_key", "direction", "interval", "amount_min", "amount_max", "category_id")}
        body["name"] = "Zinsen TR" if s["name"].startswith("Interest") else s["name"]
        if s["name"] == "Disney Plus":
            body["status"] = "ignored"
        body = {k: (str(v) if isinstance(v, D) else v) for k, v in body.items()}
        assert client.post("/api/recurring", json=body, headers=ORIGIN).status_code == 201
    res = client.get("/api/recurring").json()
    assert res["suggestions"] == []
    names = [i["name"] for i in res["items"]]
    assert "Disney Plus" not in names and "Zinsen TR" in names
    summary = {k: D(v) for k, v in res["summary"].items()}
    yearly_huk = D("412.50") * rec.monthly_factor("yearly")
    assert summary["costs"] == (D("17.99") + D("10.99") + D("890.12") + yearly_huk.quantize(D("0.01")))
    assert summary["savings"] == D("500.00")
    assert summary["income"] > D("3500")
    assert res["by_category"][0]["name"] == "Kredit & Finanzierung"

    # categories land on the transactions
    with client.app.state.sessionmaker() as db:
        netflix = db.query(Transaction).filter(Transaction.counterparty.like("Netflix%")).all()
        assert {cats[t.category_id] for t in netflix} == {"Abos & Medien"}
        rewe = db.query(Transaction).filter(Transaction.counterparty == "REWE Markt").first()
        assert rewe.category_id is None

    # change the category of a recurring payment: its transactions follow
    item = next(i for i in res["items"] if i["name"] == "Netflix International")
    new_cat = client.post("/api/categories", json={"name": "Streaming", "kind": "expense"}, headers=ORIGIN).json()
    upd = {"name": "Netflix", "interval": "monthly", "category_id": new_cat["id"], "status": "active", "note": "Premium"}
    assert client.put(f"/api/recurring/{item['id']}", json=upd, headers=ORIGIN).status_code == 200
    txs = client.get(f"/api/recurring/{item['id']}/transactions").json()
    assert len(txs) == 10 and txs[0]["amount"] == "-17.99"
    with client.app.state.sessionmaker() as db:
        assert {t.category_id for t in db.query(Transaction).filter(Transaction.counterparty.like("Netflix%")).all()} == {new_cat["id"]}

    # new booking next month is matched automatically; a missed payment shows as overdue
    with client.app.state.sessionmaker() as db:
        db.add(Transaction(account_id=ids["giro"], booking_date=date(2026, 12, 15), amount=D("-17.99"), counterparty="Netflix International B.V.", purpose="Netflix 12/2026"))
        db.commit()
        later = overview(db, date(2027, 2, 1))
    nf = next(i for i in later["items"] if i["name"] == "Netflix")
    assert nf["count"] == 11 and nf["overdue"] is True
    from finanzen.mcp.server import t_get_recurring

    with client.app.state.sessionmaker() as db:
        mcp = t_get_recurring(db, None, {})
    assert any(i["name"] == "Netflix" for i in mcp["items"]) and "costs" in mcp["summary_per_month"]
    assert client.delete(f"/api/recurring/{item['id']}", headers=ORIGIN).status_code == 204


def test_validation(client):
    login(client)
    bad = {"name": "X", "match_key": "x", "direction": "out", "interval": "daily"}
    assert client.post("/api/recurring", json=bad, headers=ORIGIN).status_code == 422
    assert client.post("/api/categories", json={"name": "X", "kind": "nope"}, headers=ORIGIN).status_code == 422
    empty = client.get("/api/recurring").json()
    assert empty["has_transactions"] is False and empty["items"] == []


def test_salary_and_expenses_from_same_payer(client):
    login(client)
    rnd = random.Random(11)
    with client.app.state.sessionmaker() as db:
        giro = Account(name="Giro", kind="giro", asset_class="cash", details={})
        db.add(giro)
        db.flush()
        for i, d in enumerate(months_back(12, 20)):
            db.add(Transaction(account_id=giro.id, booking_date=d, amount=D(str(4000 + rnd.randint(0, 300))), counterparty="Slimstock GmbH", purpose=f"LOHN / GEHALT {d:%m/%y}"))
            if i in (1, 2, 6, 7, 10):  # irregular expenses, sometimes on the salary day
                db.add(Transaction(account_id=giro.id, booking_date=d + timedelta(days=rnd.choice([0, 3, 9])), amount=D(str(rnd.randint(80, 900))), counterparty="Slimstock GmbH", purpose=f"Reisekosten {d:%m/%y}"))
        # Christmas bonus as an extra payment
        db.add(Transaction(account_id=giro.id, booking_date=date(2025, 12, 1), amount=D("2100"), counterparty="Slimstock GmbH", purpose="LOHN / GEHALT Sonderzahlung"))
        db.commit()
        data = overview(db, TODAY)
        cats = {c.id: c.name for c in db.query(Category).all()}
    salary = [s for s in data["suggestions"] if s["name"].startswith("Slimstock")]
    assert len(salary) == 1, [s["name"] for s in data["suggestions"]]
    s = salary[0]
    assert s["name"] == "Slimstock – Lohn Gehalt" and s["interval"] == "monthly" and s["direction"] == "in"
    assert cats[s["category_id"]] == "Gehalt & Lohn"
    assert s["match_key"] == "slimstock|lohn gehalt"
    body = {k: s[k] for k in ("match_key", "direction", "interval", "category_id")} | {"name": s["name"], "amount_min": None, "amount_max": None}
    assert client.post("/api/recurring", json=body, headers=ORIGIN).status_code == 201
    res = client.get("/api/recurring").json()
    item = next(i for i in res["items"] if i["name"] == "Slimstock – Lohn Gehalt")
    txs = client.get(f"/api/recurring/{item['id']}/transactions").json()
    assert txs and all("Reisekosten" not in t["purpose"] for t in txs)  # expenses stay out
    assert len(txs) == 12  # the monthly salaries; the bonus has its own purpose and is no regular payment
