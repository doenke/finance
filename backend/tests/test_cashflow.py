from datetime import date
from decimal import Decimal as D

from finanzen.models import Account, Category, Transaction
from finanzen.services.cashflow import cashflow, role_of

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}


def test_monthly_cashflow_with_roles(client):
    login(client, "Sönke Jacobs")
    with client.app.state.sessionmaker() as db:
        spk = Account(name="Sparkasse Giro", kind="giro", asset_class="cash", iban="DE11390500000000000001", details={})
        dkb = Account(name="DKB Giro", kind="giro", asset_class="cash", iban="DE22120300000000000002", details={})
        tg = Account(name="DKB Tagesgeld", kind="tagesgeld", asset_class="cash", iban="DE33120300000000000003", details={})
        depot = Account(name="DKB Depot", kind="depot", asset_class="securities", details={})
        rente = Account(name="Riester", kind="altersvorsorge", asset_class="pension", details={})
        db.add_all([spk, dkb, tg, depot, rente])
        db.flush()
        savings_cat = db.query(Category).filter(Category.name == "Sparen & Anlegen").one()

        def tx(acc, d, amount, cp, purpose="", category=None, raw=None):
            db.add(Transaction(account_id=acc.id, booking_date=d, amount=D(amount), counterparty=cp, purpose=purpose, category_id=category, raw=raw))

        d = date(2026, 10, 1)
        tx(spk, date(2026, 10, 28), "4000", "Slimstock GmbH", "LOHN / GEHALT 10/26")
        tx(spk, date(2026, 10, 5), "-480.20", "REWE Markt", "Kartenzahlung")
        tx(spk, date(2026, 10, 6), "-58.98", "Telefonica Germany", "Ihre Tarifrechnung")
        tx(spk, date(2026, 10, 3), "-162", "DekaBank", "Riester Beitrag", savings_cat.id)
        # Sparkasse -> DKB Giro (both everyday accounts): not counted
        tx(spk, date(2026, 10, 2), "-2900", "Ulrike Jacobs", "Spass", raw={"IBAN Zahlungsbeteiligter": "DE22120300000000000002"})
        tx(dkb, d, "2900", "Ulrike Jacobs", "Spass")
        # DKB Giro -> Tagesgeld: saved
        tx(dkb, date(2026, 10, 16), "-971.95", "Herr Sönke Jacobs", "Sparen")
        tx(tg, date(2026, 10, 17), "971.95", "Herr Sönke Jacobs", "Sparen")
        # back from Tagesgeld for the holidays: reduces the savings
        tx(tg, date(2026, 10, 20), "-300.55", "Sönke Jacobs", "Urlaub")
        tx(dkb, date(2026, 10, 21), "300.55", "Sönke Jacobs", "Urlaub")
        # loan installment paid from DKB Giro is spending
        tx(dkb, d, "-1400.30", "Deutsche Bank AG", "Baufinanzierung")
        # interest on the Tagesgeld stays in the saving sphere
        tx(tg, date(2026, 10, 1), "12.30", "DKB", "Zinsen")
        db.commit()
        assert role_of(spk) == "spending" and role_of(tg) == "saving" and role_of(depot) == "saving" and role_of(rente) is None
        data = cashflow(db, months=2, month="2026-10", end=date(2026, 10, 31))
    oct_ = next(m for m in data["months"] if m["month"] == "2026-10")
    assert oct_["income"] == D("4000")
    assert oct_["expenses"] == D("480.20") + D("58.98") + D("1400.30")
    assert oct_["savings"] == D("162") + D("971.95") - D("300.55")
    assert abs(oct_["savings_rate"] - float((D("162") + D("971.95") - D("300.55")) / D("4000"))) < 1e-9
    assert oct_["rest"] == oct_["income"] - oct_["expenses"] - oct_["savings"]
    routes = {s["name"]: s["amount"] for s in data["detail"]["savings"]}
    assert routes["DKB Giro → DKB Tagesgeld"] == D("971.95") - D("300.55")
    assert any(n.startswith("Sparen & Anlegen") for n in routes)
    exp = {e["name"]: e["amount"] for e in data["detail"]["expenses"]}
    assert exp["Telefon & Internet"] == D("58.98")  # guessed from keywords
    assert {a["name"] for a in data["accounts"]} == {"Sparkasse Giro", "DKB Giro", "DKB Tagesgeld", "DKB Depot"}


def test_flow_role_override(client):
    login(client)
    with client.app.state.sessionmaker() as db:
        joint = Account(name="Gemeinschaftskonto", kind="giro", asset_class="cash", details={})
        db.add(joint)
        db.commit()
        joint_id = joint.id
    res = client.put(f"/api/accounts/{joint_id}/flow-role", json={"role": "saving"}, headers=ORIGIN).json()
    assert res == {"id": joint_id, "role": "saving", "automatic": False}
    res = client.put(f"/api/accounts/{joint_id}/flow-role", json={"role": None}, headers=ORIGIN).json()
    assert res["role"] == "spending" and res["automatic"] is True
    assert client.put(f"/api/accounts/{joint_id}/flow-role", json={"role": "x"}, headers=ORIGIN).status_code == 422
    assert client.get("/api/cashflow").status_code == 200
