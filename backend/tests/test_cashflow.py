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
    phone = next(e for e in data["detail"]["expenses"] if e["name"] == "Telefon & Internet")
    assert sum(D(b["amount"]) for b in phone["bookings"]) == -D("58.98")  # the single bookings behind the sum
    assert all(b["account"] and str(b["date"]).startswith(data["month"]) for b in phone["bookings"])
    route = next(e for e in data["detail"]["savings"] if e["name"] == "DKB Giro → DKB Tagesgeld")
    assert len(route["bookings"]) == 2
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


def test_category_rules(client):
    login(client)
    with client.app.state.sessionmaker() as db:
        giro = Account(name="Giro", kind="giro", asset_class="cash", details={})
        db.add(giro)
        db.flush()
        for k in range(6):
            d = date(2026, 10, 1 + k)
            db.add(Transaction(account_id=giro.id, booking_date=d, amount=D("-45.10"), counterparty="REWE SAGT DANKE. 43655260/Bardenberg", purpose="Debitk.12"))
            db.add(Transaction(account_id=giro.id, booking_date=d, amount=D("-12.00"), counterparty="Kiosk am Eck", purpose="Kartenzahlung"))
            db.add(Transaction(account_id=giro.id, booking_date=d, amount=D("-19.39"), counterparty="PayPal Europe S.a.r.l. et Cie S.C.A", purpose="1054/PP.7863.PP/. Takeaway.com Payments B.V., Ihr Einkauf bei Takeaway.com"))
        db.add(Transaction(account_id=giro.id, booking_date=date(2026, 10, 28), amount=D("3000"), counterparty="Arbeitgeber", purpose="Gehalt"))
        db.commit()
        giro_id = giro.id
        cats = {c.name: c.id for c in db.query(Category).all()}
        data = cashflow(db, months=1, month="2026-10", end=date(2026, 10, 31))
    exp = {e["name"]: D(e["amount"]) for e in data["detail"]["expenses"]}
    # built-in keywords know REWE and Takeaway; the kiosk is unknown
    assert exp["Lebensmittel & Drogerie"] == D("270.60") and exp["Restaurant & Lieferdienst"] == D("116.34")
    assert exp["Ohne Kategorie"] == D("72.00")
    group = data["unknown_groups"][0]
    assert group["pattern"] == "kiosk" and group["count"] == 6 and D(group["total"]) == D("72.00")

    preview = client.post("/api/category-rules/preview", json={"pattern": "Kiosk", "direction": "out"}, headers=ORIGIN).json()
    assert preview["count"] == 6 and D(preview["total"]) == D("72.00") and preview["examples"][0]["current"] is None
    bad = client.post("/api/category-rules", json={"pattern": "Kiosk"}, headers=ORIGIN)
    assert bad.status_code == 422  # no category
    rule = client.post("/api/category-rules", json={"pattern": "Kiosk", "direction": "out", "category_id": cats["Lebensmittel & Drogerie"]}, headers=ORIGIN).json()
    assert rule["count"] == 6 and rule["category"] == "Lebensmittel & Drogerie"
    # an own rule beats the built-in keyword: Takeaway -> Einkaufen (only on this account)
    client.post("/api/category-rules", json={"pattern": "takeaway", "field": "purpose", "account_id": giro_id, "category_id": cats["Einkaufen"]}, headers=ORIGIN)
    with client.app.state.sessionmaker() as db:
        data = cashflow(db, months=1, month="2026-10", end=date(2026, 10, 31))
    exp = {e["name"]: D(e["amount"]) for e in data["detail"]["expenses"]}
    assert exp["Lebensmittel & Drogerie"] == D("342.60") and exp["Einkaufen"] == D("116.34") and "Ohne Kategorie" not in exp
    assert data["unknown_groups"] == []
    rules = client.get("/api/category-rules").json()
    assert [r["pattern"] for r in rules] == ["takeaway", "Kiosk"]  # longer pattern first
    upd = client.put(f"/api/category-rules/{rule['id']}", json={"pattern": "kiosk am", "category_id": cats["Einkaufen"]}, headers=ORIGIN).json()
    assert upd["count"] == 6 and upd["category"] == "Einkaufen"
    assert client.delete(f"/api/category-rules/{rule['id']}", headers=ORIGIN).status_code == 204
    assert len(client.get("/api/category-rules").json()) == 1


    # a single booking assigned by hand beats rules and keywords; null goes back to automatic
    with client.app.state.sessionmaker() as db:
        data = cashflow(db, months=1, month="2026-10", end=date(2026, 10, 31))
    food = next(e for e in data["detail"]["expenses"] if e["name"] == "Lebensmittel & Drogerie")
    b = food["bookings"][0]
    assert b["category_source"] == "keyword" and b["assignable"] is True
    res = client.put(f"/api/transactions/{b['id']}/category", json={"category_id": cats["Bargeld"]}, headers=ORIGIN)
    assert res.status_code == 200
    with client.app.state.sessionmaker() as db:
        data = cashflow(db, months=1, month="2026-10", end=date(2026, 10, 31))
    cash = next(e for e in data["detail"]["expenses"] if e["name"] == "Bargeld")
    assert cash["bookings"][0]["id"] == b["id"] and cash["bookings"][0]["category_source"] == "fixed"
    assert client.put(f"/api/transactions/{b['id']}/category", json={"category_id": None}, headers=ORIGIN).json()["category_id"] is None
    assert client.put(f"/api/transactions/{b['id']}/category", json={"category_id": 99999}, headers=ORIGIN).status_code == 422
    assert client.put("/api/transactions/99999/category", json={"category_id": None}, headers=ORIGIN).status_code == 404


def test_mcp_category_tools(client):
    from finanzen.mcp.server import t_create_category, t_create_category_rule, t_list_categories, t_set_recurring_category
    from finanzen.models import RecurringPayment

    login(client)
    with client.app.state.sessionmaker() as db:
        giro = Account(name="Giro", kind="giro", asset_class="cash", details={})
        db.add(giro)
        db.flush()
        other = db.query(Category).filter(Category.name == "Sonstige Ausgaben").one()
        for m in range(1, 7):
            db.add(Transaction(account_id=giro.id, booking_date=date(2026, m, 12), amount=D("-400"), counterparty="Advanzia Bank S.A.", purpose="Advanzia MasterCard Zahlung", category_id=other.id))
        db.add(RecurringPayment(name="Advanzia Bank", match_key="advanzia bank", direction="out", interval="monthly", category_id=other.id))
        db.commit()
        created = t_create_category(db, None, {"name": "Kreditkarte"})
        assert created["created"] and created["category"]["kind"] == "expense"
        assert t_create_category(db, None, {"name": "kreditkarte"})["created"] is False
        rule = t_create_category_rule(db, None, {"pattern": "advanzia", "category": "Kreditkarte"})
        assert rule["count"] == 6
        assert t_set_recurring_category(db, None, {"recurring": "Advanzia", "category": "Kreditkarte"})["updated"]
        kk = created["category"]["id"]
        db.expire_all()
        assert {t.category_id for t in db.query(Transaction).all()} == {kk}
        assert any(c["name"] == "Kreditkarte" for c in t_list_categories(db, None, {}))
