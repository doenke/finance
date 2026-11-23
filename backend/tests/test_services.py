from datetime import date
from decimal import Decimal as D

from finanzen.services.deposit import deposit_value
from finanzen.services.holdings import TradeIn, build_positions
from finanzen.services.loan import LoanTerms, Prepayment, add_months, balance_at, days360, expand_planned, schedule


def test_fifo_cost_and_realized_gain():
    trades = [
        TradeIn(date(2024, 1, 10), "buy", 1, D("10"), D("1000"), D("5")),
        TradeIn(date(2024, 6, 1), "buy", 1, D("10"), D("1200"), D("5")),
        TradeIn(date(2025, 1, 5), "sell", 1, D("15"), D("1800"), D("6")),
        TradeIn(date(2025, 3, 1), "dividend", 1, amount=D("12.50"), taxes=D("3.30")),
    ]
    pos = build_positions(trades)[1]
    assert pos.quantity == D("5")
    # remaining: half of the second lot (1205 / 2)
    assert pos.cost == D("602.5")
    # sold 10 of lot 1 (1005) + 5 of lot 2 (602.5) for 1800 - 6 fees
    assert pos.realized == D("1800") - D("6") - D("1005") - D("602.5")
    assert pos.income == D("12.50")
    assert pos.taxes == D("3.30")


def test_split_and_until():
    trades = [
        TradeIn(date(2024, 1, 1), "buy", 7, D("2"), D("200")),
        TradeIn(date(2024, 5, 1), "split", 7, D("4")),
    ]
    assert build_positions(trades, until=date(2024, 4, 30))[7].quantity == D("2")
    pos = build_positions(trades)[7]
    assert pos.quantity == D("8")
    assert pos.cost == D("200")


def test_annuity_schedule():
    terms = LoanTerms(
        principal=D("100000"), disbursed_on=date(2024, 1, 1), rate=D("3"), first_payment=date(2024, 1, 30), initial_repayment=D("2")
    )
    rows = schedule(terms)
    first, second = rows[0], rows[1]
    assert first.payment == D("416.67")
    assert first.interest == D("241.67")  # 29 days (30/360) of 3 % on 100,000
    assert second.interest == (first.balance * D("0.03") / 12).quantize(D("0.01"))
    assert rows[-1].balance == 0
    assert 25 < (rows[-1].date.year - 2024) < 35  # 3 % / 2 % initial repayment ends after ~30 years
    assert sum(r.principal + r.prepayment for r in rows) == D("100000")


def test_prepayments_shorten_the_loan():
    terms = LoanTerms(principal=D("100000"), disbursed_on=date(2024, 1, 1), rate=D("3"), first_payment=date(2024, 2, 1), installment=D("500"))
    base = schedule(terms)
    planned = expand_planned([{"date": "2024-12-15", "amount": "5000", "repeat": "yearly"}], until=date(2060, 1, 1))
    faster = schedule(terms, planned)
    assert faster[-1].date < base[-1].date
    assert sum(r.interest for r in faster) < sum(r.interest for r in base)
    assert any(r.prepayment == D("5000") and r.planned for r in faster)
    assert balance_at(faster, D("100000"), date(2024, 12, 31)) < balance_at(base, D("100000"), date(2024, 12, 31)) - D("4999")


def test_schedule_anchored_on_bank_balance_and_grace():
    terms = LoanTerms(
        principal=D("50000"), disbursed_on=date(2023, 1, 1), rate=D("2"), first_payment=date(2023, 2, 1), installment=D("300"), grace_until=date(2023, 12, 31)
    )
    rows = schedule(terms)
    assert rows[0].principal == 0 and rows[0].payment == rows[0].interest
    anchored = schedule(terms, [Prepayment(date(2025, 3, 1), D("1000"))], start_balance=D("40000"), start_date=date(2025, 1, 15))
    assert anchored[0].date == date(2025, 2, 1)
    assert anchored[0].interest == (D("40000") * D("0.02") * days360(date(2025, 1, 15), date(2025, 2, 1)) / 360).quantize(D("0.01"))
    assert any(r.prepayment == D("1000") for r in anchored)


def test_fixed_repayment_and_helpers():
    terms = LoanTerms(principal=D("12000"), disbursed_on=date(2024, 1, 1), rate=D("6"), first_payment=date(2024, 2, 1), mode="fixed_repayment", installment=D("1000"))
    rows = schedule(terms)
    assert len(rows) == 12
    assert all(r.principal == D("1000") for r in rows)
    assert rows[1].interest == D("55.00")
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert days360(date(2024, 1, 15), date(2024, 2, 15)) == 30


def test_deposit_accrual():
    assert deposit_value(D("10000"), D("3"), date(2025, 1, 1), date(2026, 1, 1), date(2026, 1, 1)) == D("10300.00")
    assert deposit_value(D("10000"), D("3"), date(2025, 1, 1), date(2026, 1, 1), date(2027, 6, 1)) == D("10300.00")
    assert deposit_value(D("10000"), D("3"), date(2025, 1, 1), date(2026, 1, 1), date(2025, 7, 2)) == D("10148.48")
    assert deposit_value(D("10000"), D("3"), date(2024, 1, 1), None, date(2023, 12, 1)) == 0


def test_installment_change():
    terms = LoanTerms(principal=D("100000"), disbursed_on=date(2024, 1, 1), rate=D("3"), first_payment=date(2024, 2, 1), installment=D("500"))
    base = schedule(terms)
    higher = schedule(terms, installment_changes=[(date(2025, 1, 1), D("1000"))])
    assert all(r.payment == D("500") for r in higher if date(2024, 2, 1) <= r.date < date(2025, 1, 1))
    assert next(r for r in higher if r.date >= date(2025, 1, 1)).payment == D("1000")
    assert higher[-1].date < base[-1].date
    assert higher[-1].balance == 0
