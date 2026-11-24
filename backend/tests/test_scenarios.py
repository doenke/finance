from datetime import date
from decimal import Decimal as D

from .conftest import login

ORIGIN = {"Origin": "https://finanzen.example.org"}


def test_loan_scenarios(client):
    login(client)
    loan = client.post(
        "/api/accounts",
        json={
            "name": "Baufinanzierung",
            "kind": "kredit",
            "details": {
                "principal": "200000",
                "disbursed_on": "2024-01-01",
                "rate": "3.5",
                "first_payment": "2024-02-01",
                "initial_repayment": "2",
                "fixed_until": "2034-01-31",
                "planned_prepayments": [{"date": f"{date.today().year}-12-15", "amount": "5000", "repeat": "yearly"}],
            },
        },
        headers=ORIGIN,
    ).json()
    body = {
        "scenarios": [
            {"name": "Mit Plan"},
            {"name": "Höhere Rate", "include_planned": False, "installment": "1500", "installment_from": "2027-01-01"},
            {"name": "Anschluss 5 %", "include_planned": False, "followup_rate": "5"},
            {"name": "Extra 20.000", "include_planned": False, "extra_prepayments": [{"date": "2028-06-01", "amount": "20000"}]},
        ],
        "save": True,
    }
    res = client.post(f"/api/accounts/{loan['id']}/scenarios", json=body, headers=ORIGIN).json()
    by = {r["name"]: r for r in res["results"]}
    base = by["Ohne Sondertilgungen"]
    assert D(base["interest_saved"]) == 0 and base["months_saved"] == 0
    for name in ("Mit Plan", "Höhere Rate", "Extra 20.000"):
        assert D(by[name]["interest_saved"]) > 0, name
        assert by[name]["months_saved"] > 0, name
    assert D(by["Anschluss 5 %"]["interest_saved"]) < 0  # higher follow-up rate costs more
    assert by["Anschluss 5 %"]["balance_at_fixed_until"] == base["balance_at_fixed_until"]
    assert D(by["Extra 20.000"]["balance_at_fixed_until"]) < D(base["balance_at_fixed_until"])
    assert base["series"][-1]["balance"] in ("0", "0.00", 0) or D(base["series"][-1]["balance"]) == 0
    # saved for next time
    acc = client.get(f"/api/accounts/{loan['id']}").json()
    assert len(acc["details"]["scenarios"]) == 4
    too_many = client.post(f"/api/accounts/{loan['id']}/scenarios", json={"scenarios": [{}] * 5}, headers=ORIGIN)
    assert too_many.status_code == 422


def test_fee_increases_loan_balance_like_the_bank():
    """Bank statement balance, a fee for changing the installment and a prepayment (numbers from a real plan)."""
    from datetime import date
    from decimal import Decimal as Dec

    from finanzen.services.loan import LoanTerms, Prepayment, schedule

    terms = LoanTerms(
        principal=Dec("268000"), disbursed_on=date(2019, 3, 1), rate=Dec("1.94"), first_payment=date(2019, 4, 1),
        installment=Dec("1002"), installment_changes=((date(2026, 7, 1), Dec("1400.30")),),
    )
    events = [Prepayment(date(2026, 8, 1), Dec("13400")), Prepayment(date(2026, 7, 1), Dec("300"), fee=True)]
    rows = schedule(terms, events, start_balance=Dec("144874.40"), start_date=date(2026, 3, 1))
    by_date = {}
    for r in rows:
        by_date.setdefault(r.date, []).append(r)
    fee_row, july = by_date[date(2026, 7, 1)]
    assert fee_row.fee == Dec("300") and fee_row.balance == Dec("142867.31")  # fee comes before the payment
    assert july.interest == Dec("230.97") and july.payment == Dec("1400.30")
    assert by_date[date(2026, 8, 1)][0].balance == Dec("127126.76")  # after payment and prepayment
    assert by_date[date(2026, 11, 1)][0].balance == Dec("123536.63")  # same as the bank's plan


def test_fee_transaction_in_schedule_api(client):
    from .conftest import login

    origin = {"Origin": "https://finanzen.example.org"}
    login(client)
    acc = client.post(
        "/api/accounts",
        json={"name": "Kredit", "kind": "kredit", "details": {"principal": "100000", "disbursed_on": "2025-01-01", "rate": "3", "first_payment": "2025-02-01", "installment": "800"}},
        headers=origin,
    ).json()
    before = client.get(f"/api/accounts/{acc['id']}/schedule").json()
    assert client.post(f"/api/accounts/{acc['id']}/transactions", json={"booking_date": "2025-06-01", "amount": "250", "kind": "fee", "purpose": "Ratenänderung"}, headers=origin).status_code == 201
    after = client.get(f"/api/accounts/{acc['id']}/schedule").json()
    fee_rows = [r for r in after["rows"] if r["fee"] != "0" and float(r["fee"]) > 0]
    assert len(fee_rows) == 1 and fee_rows[0]["date"] == "2025-06-01"
    assert float(after["rows"][-1]["date"][:4]) >= float(before["rows"][-1]["date"][:4])
    assert len(after["rows"]) > len(before["rows"])  # longer: the fee is paid off too
