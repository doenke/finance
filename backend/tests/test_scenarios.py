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
