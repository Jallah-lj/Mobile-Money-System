"""Core transaction tests: fees, balances, limits — against a real (temp) SQLite DB."""

from decimal import Decimal


def test_transfer_fee_free_tier(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user

    sender_start = um.get_user(alice).balance
    receiver_start = um.get_user(bob).balance

    success, msg = tm.transfer(alice, bob, 100.0, "Fee Test")
    assert success, msg

    fee = Decimal("100") * Decimal("0.01")
    assert um.get_user(alice).balance == sender_start - Decimal("100") - fee
    assert um.get_user(bob).balance == receiver_start + Decimal("100")


def test_transfer_insufficient_funds(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    success, msg = tm.transfer(alice, bob, 99_999_999.0)
    assert not success
    assert "Insufficient" in msg or "limit" in msg.lower()


def test_transfer_to_self_rejected(verified_user):
    alice, um, tm = verified_user
    success, msg = tm.transfer(alice, alice, 10.0)
    assert not success
    assert "self" in msg.lower()


def test_transfer_to_unknown_rejected(verified_user):
    alice, um, tm = verified_user
    success, msg = tm.transfer(alice, "+2349999999999", 10.0)
    assert not success


def test_withdrawal_fee_and_balance(verified_user):
    alice, um, tm = verified_user
    start = um.get_user(alice).balance
    success, msg = tm.withdraw(alice, 100.0)
    assert success, msg
    # 1% withdrawal fee for free tier
    assert um.get_user(alice).balance == start - Decimal("100") - Decimal("1.00")


def test_withdrawal_insufficient_funds(verified_user):
    alice, um, tm = verified_user
    success, msg = tm.withdraw(alice, 99_999_999.0)
    assert not success


def test_deposit_increases_balance(verified_user):
    alice, um, tm = verified_user
    start = um.get_user(alice).balance
    success, msg = tm.deposit(alice, 250.0)
    assert success, msg
    assert um.get_user(alice).balance == start + Decimal("250.0")


def test_pay_bill_fee(verified_user):
    alice, um, tm = verified_user
    start = um.get_user(alice).balance
    success, msg = tm.pay_bill(alice, 50.0, "LEC Power", "MTR-123")
    assert success, msg
    # Flat $0.50 fee for free tier
    assert um.get_user(alice).balance == start - Decimal("50.0") - Decimal("0.50")


def test_ledger_stays_balanced(verified_user, second_verified_user):
    """Every posted ledger batch must sum to zero (double-entry invariant)."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.transfer(alice, bob, 100.0)
    tm.withdraw(alice, 50.0)
    tm.pay_bill(alice, 20.0, "Water", "ACC-1")

    from mobile_money_system.database import get_db
    with get_db() as conn:
        total = conn.execute("SELECT SUM(CAST(amount AS REAL)) FROM ledger").fetchone()[0]
    assert total == 0.0
