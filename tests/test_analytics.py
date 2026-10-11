"""Tier 3: personal analytics & account statements (pure functions + DB invariant)."""

from decimal import Decimal

import pytest

from mobile_money_system.analytics import (
    budget_status,
    in_month,
    month_bounds,
    monthly_statement,
    monthly_totals,
    net_flow,
    spending_by_category,
    top_counterparties,
)
from mobile_money_system.models import Transaction, utcnow

ALICE = "+2348012345678"
BOB = "+2348087654321"


def _txn(t_id, sender, receiver, amount, t_type, ts, status="COMPLETED", desc=""):
    return Transaction(id=t_id, sender_phone=sender, receiver_phone=receiver,
                       amount=Decimal(str(amount)), currency="USD", type=t_type,
                       timestamp=ts, description=desc, status=status)


def _sample_history():
    """A small history spanning two months for ALICE."""
    return [
        # --- September 2026 ---
        _txn("t1", "SYSTEM", ALICE, 10000, "DEPOSIT", "2026-09-01T10:00:00"),
        _txn("t2", ALICE, BOB, 100, "TRANSFER", "2026-09-05T10:00:00"),
        _txn("t3", ALICE, "SYSTEM", 50, "WITHDRAWAL", "2026-09-10T10:00:00"),
        _txn("t4", ALICE, "SYSTEM_REVENUE", 0.25, "FEE", "2026-09-10T10:00:01"),
        # --- October 2026 ---
        _txn("t5", ALICE, BOB, 200, "TRANSFER", "2026-10-02T10:00:00"),
        _txn("t6", ALICE, "BILLER_SYSTEM", 20, "BILL_PAYMENT", "2026-10-03T10:00:00"),
        _txn("t7", ALICE, "SYSTEM_REVENUE", 0.25, "FEE", "2026-10-03T10:00:01"),
        _txn("t8", BOB, ALICE, 30, "TRANSFER", "2026-10-04T10:00:00"),   # income
        _txn("t9", BOB, ALICE, 999, "REQUEST", "2026-10-05T10:00:00", status="PENDING"),  # no flow
    ]


def test_month_bounds_and_in_month():
    start, end = month_bounds(2026, 10)
    assert start == "2026-10-01T00:00:00"
    assert end == "2026-11-01T00:00:00"
    start, end = month_bounds(2026, 12)
    assert end == "2027-01-01T00:00:00"
    assert in_month("2026-10-15T12:00:00", 2026, 10)
    assert not in_month("2026-11-01T00:00:00", 2026, 10)
    assert not in_month("2026-09-30T23:59:59", 2026, 10)


def test_net_flow():
    t = _txn("x", ALICE, BOB, 100, "TRANSFER", "2026-10-01T00:00:00")
    assert net_flow(t, ALICE) == Decimal("-100")
    assert net_flow(t, BOB) == Decimal("100")
    assert net_flow(t, "+2349999999999") == Decimal("0")
    fee = _txn("y", ALICE, "SYSTEM_REVENUE", 0.25, "FEE", "2026-10-01T00:00:00")
    assert net_flow(fee, ALICE) == Decimal("-0.25")
    req = _txn("z", BOB, ALICE, 50, "REQUEST", "2026-10-01T00:00:00", status="PENDING")
    assert net_flow(req, ALICE) == Decimal("0")  # pending requests move no money


def test_monthly_totals():
    history = _sample_history()
    totals = monthly_totals(history, ALICE, months=2, now=utcnow().replace(year=2026, month=10, day=15))
    assert [t["month"] for t in totals] == ["2026-09", "2026-10"]
    sep, oct_ = totals
    assert sep["income"] == Decimal("10000")       # the September deposit
    assert sep["spending"] == Decimal("150")       # 100 transfer + 50 withdrawal
    assert sep["fees"] == Decimal("0.25")
    assert oct_["income"] == Decimal("30")
    assert oct_["spending"] == Decimal("220")      # 200 transfer + 20 bill
    assert oct_["fees"] == Decimal("0.25")


def test_spending_by_category():
    history = _sample_history()
    cats = spending_by_category(history, ALICE)
    assert cats["P2P Transfers"] == Decimal("300")
    assert cats["Withdrawals"] == Decimal("50")
    assert cats["Bill Payments"] == Decimal("20")
    assert cats["Fees"] == Decimal("0.50")
    # Month-scoped
    cats_oct = spending_by_category(history, ALICE, 2026, 10)
    assert cats_oct["P2P Transfers"] == Decimal("200")
    assert "Withdrawals" not in cats_oct


def test_top_counterparties():
    history = _sample_history()
    top = top_counterparties(history, ALICE, n=5)
    assert len(top) == 1
    assert top[0]["phone"] == BOB
    assert top[0]["amount"] == Decimal("300")
    assert top[0]["count"] == 2
    # BOB's only outgoing transfer is the 30 payback to ALICE
    top_bob = top_counterparties(history, BOB)
    assert len(top_bob) == 1 and top_bob[0]["phone"] == ALICE
    assert top_bob[0]["amount"] == Decimal("30")


def test_monthly_statement_balances():
    history = _sample_history()
    stmt = monthly_statement(history, ALICE, 2026, 10)
    # Opening = everything before October: +10000 -100 -50 -0.25
    assert stmt["opening_balance"] == Decimal("9849.75")
    assert stmt["income"] == Decimal("30")
    assert stmt["spending"] == Decimal("220")
    assert stmt["fees"] == Decimal("0.25")
    # Closing = opening + income - spending - fees = 9659.50
    assert stmt["closing_balance"] == Decimal("9659.50")
    # All 5 October rows appear (incl. the pending REQUEST — shown, but moves no money)
    assert stmt["tx_count"] == 5
    # Transactions are chronological and month-scoped
    assert [t.id for t in stmt["transactions"]] == ["t5", "t6", "t7", "t8", "t9"]


def test_budget_status():
    history = _sample_history()
    bs = budget_status(history, ALICE, Decimal("500"), 2026, 10)
    assert bs["spent"] == Decimal("220.25")        # 200 transfer + 20 bill + 0.25 fee
    assert bs["remaining"] == Decimal("279.75")
    assert bs["pct"] == pytest.approx(44.05)
    # No budget set -> pct None
    bs0 = budget_status(history, ALICE, Decimal("0"), 2026, 10)
    assert bs0["pct"] is None


def test_statement_closing_matches_real_balance(managers, verified_user, second_verified_user):
    """DB-backed invariant: with complete history, statement closing == live balance."""
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user

    tm.transfer(phone, bob_phone, 100, "groceries")
    tm.transfer(phone, bob_phone, 200, "rent share")
    tm.withdraw(phone, 50, "cash")
    tm.pay_bill(phone, 20, "LEC Power", "MTR-1", "electricity")
    tm.transfer(bob_phone, phone, 30, "payback")

    now = utcnow()
    history = tm.get_history(phone)
    stmt = monthly_statement(history, phone, now.year, now.month)
    assert stmt["closing_balance"] == um.get_user(phone).balance
    # The seed credit lands in the current month -> opening is 0, income includes it
    assert stmt["opening_balance"] == Decimal("0")
    assert stmt["income"] == Decimal("10030")      # 10000 seed + 30 payback


def test_monthly_budget_roundtrip(managers, verified_user):
    phone, um, tm = verified_user
    ok, _ = um.update_user(phone, monthly_budget="750.25")
    assert ok
    assert um.get_user(phone).monthly_budget == Decimal("750.25")
    # Default for pre-migration users
    assert um.get_user(phone).monthly_budget is not None
