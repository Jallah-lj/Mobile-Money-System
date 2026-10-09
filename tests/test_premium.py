"""Premium membership tier tests: subscription, perks, limits, loyalty points."""

from datetime import timedelta
from decimal import Decimal

import pytest

from mobile_money_system import premium as P
from mobile_money_system.models import utcnow


# --- Subscription flow ------------------------------------------------------

def test_subscribe_success(verified_user):
    alice, um, tm = verified_user
    start = um.get_user(alice).balance

    success, msg = tm.subscribe_premium(alice, 1)
    assert success, msg

    user = um.get_user(alice)
    assert user.tier == "premium"
    assert user.balance == start - P.PREMIUM_MONTHLY_FEE
    assert user.premium_expires > utcnow().isoformat()
    assert um.is_premium(alice)

    # A SUBSCRIPTION transaction was recorded
    txns = tm.get_history(alice)
    sub = next(t for t in txns if t.type == "SUBSCRIPTION")
    assert sub.amount == P.PREMIUM_MONTHLY_FEE
    assert sub.receiver_phone == "SYSTEM_REVENUE"


def test_subscribe_requires_kyc(managers):
    um, tm = managers
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    tm.deposit  # user is unverified; deposit would be blocked, so fund via admin
    tm.admin_adjust_balance("+2348012345678", 100.0, "seed")

    success, msg = tm.subscribe_premium("+2348012345678", 1)
    assert not success
    assert "KYC" in msg


def test_subscribe_insufficient_funds(verified_user):
    alice, um, tm = verified_user
    um.update_user(alice, balance=Decimal("1.0"))
    success, msg = tm.subscribe_premium(alice, 1)
    assert not success
    assert "Insufficient" in msg


def test_subscribe_renewal_stacks(verified_user):
    alice, um, tm = verified_user
    assert tm.subscribe_premium(alice, 1)[0]
    first_expiry = um.get_user(alice).premium_expires

    assert tm.subscribe_premium(alice, 2)[0]
    user = um.get_user(alice)
    # 2 more months stacked on top of the remaining first month
    expected = (utcnow() + timedelta(days=3 * P.PREMIUM_PERIOD_DAYS)).date().isoformat()
    assert user.premium_expires[:10] == expected
    assert user.premium_expires > first_expiry


def test_expired_premium_loses_perks(verified_user):
    alice, um, tm = verified_user
    assert tm.subscribe_premium(alice, 1)[0]
    assert um.is_premium(alice)

    # Force expiry into the past
    past = (utcnow() - timedelta(days=1)).isoformat()
    um.update_user(alice, premium_expires=past)

    assert not um.is_premium(alice)
    assert P.transfer_fee_rate(um.get_user(alice)) == P.FREE_TRANSFER_FEE_RATE


# --- Fee perks ---------------------------------------------------------------

def test_premium_transfer_fee_is_zero(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.subscribe_premium(alice, 1)
    start = um.get_user(alice).balance

    success, msg = tm.transfer(alice, bob, 100.0)
    assert success, msg
    # Sender pays exactly the amount — no fee
    assert um.get_user(alice).balance == start - Decimal("100.0")
    # No FEE transaction was created for a zero-fee transfer
    assert not any(t.type == "FEE" for t in tm.get_history(alice))


def test_premium_withdrawal_fee_half(verified_user):
    alice, um, tm = verified_user
    tm.subscribe_premium(alice, 1)
    start = um.get_user(alice).balance

    success, msg = tm.withdraw(alice, 100.0)
    assert success, msg
    assert um.get_user(alice).balance == start - Decimal("100.0") - Decimal("0.50")  # 0.5%


def test_premium_bill_fee_half(verified_user):
    alice, um, tm = verified_user
    tm.subscribe_premium(alice, 1)
    start = um.get_user(alice).balance

    success, msg = tm.pay_bill(alice, 50.0, "LEC Power", "MTR-1")
    assert success, msg
    assert um.get_user(alice).balance == start - Decimal("50.0") - Decimal("0.25")


def test_free_tier_fees_unchanged(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    assert P.transfer_fee_rate(um.get_user(alice)) == Decimal("0.01")
    assert P.withdrawal_fee_rate(um.get_user(alice)) == Decimal("0.01")
    assert P.bill_fee(um.get_user(alice)) == Decimal("0.50")


# --- Limits ------------------------------------------------------------------

def test_premium_limit_is_10x(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    um.update_user(alice, balance=Decimal("100000"))
    um.update_user(alice, risk_tier="high")  # high tier base: 50k -> premium: 500k

    # Free tier standard user is blocked at 5,000 (covered in compliance tests);
    # premium user can move far more than the free limit.
    tm.subscribe_premium(alice, 1)
    success, msg = tm.transfer(alice, bob, 60000.0)
    assert success, msg


def test_premium_limit_scales_with_risk_tier(verified_user):
    alice, um, tm = verified_user
    tm.subscribe_premium(alice, 1)
    # standard risk tier: 5,000 * 10 = 50,000
    assert P.transaction_limit(um.get_user(alice)) == Decimal("50000")
    um.update_user(alice, risk_tier="low")
    assert P.transaction_limit(um.get_user(alice)) == Decimal("10000")


# --- Loyalty points -----------------------------------------------------------

def test_loyalty_points_accrue_for_premium_only(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user

    # Free tier: no points
    tm.transfer(alice, bob, 100.0)
    assert um.get_user(alice).loyalty_points == 0

    # Premium: 1 point per $10
    tm.subscribe_premium(alice, 1)
    tm.transfer(alice, bob, 100.0)
    assert um.get_user(alice).loyalty_points == 10

    tm.withdraw(alice, 200.0)
    assert um.get_user(alice).loyalty_points == 30


def test_redeem_points_for_free_month(verified_user):
    alice, um, tm = verified_user
    tm.subscribe_premium(alice, 1)
    um.add_loyalty_points(alice, P.POINTS_FOR_FREE_MONTH)
    expiry_before = um.get_user(alice).premium_expires

    success, msg = tm.redeem_points_for_premium(alice)
    assert success, msg

    user = um.get_user(alice)
    assert user.loyalty_points == 0
    assert user.premium_expires > expiry_before
    assert um.is_premium(alice)


def test_redeem_points_insufficient(verified_user):
    alice, um, tm = verified_user
    success, msg = tm.redeem_points_for_premium(alice)
    assert not success
    assert "points" in msg.lower()


def test_redeem_points_activates_premium_for_free_user(verified_user):
    alice, um, tm = verified_user
    assert not um.is_premium(alice)
    um.add_loyalty_points(alice, P.POINTS_FOR_FREE_MONTH)

    success, msg = tm.redeem_points_for_premium(alice)
    assert success, msg
    assert um.is_premium(alice)


# --- Fee schedule summary ------------------------------------------------------

def test_fee_schedule_summary(verified_user):
    alice, um, tm = verified_user
    schedule = tm.get_subscription_status(alice)
    assert schedule["tier"] == "free"
    assert schedule["transfer_fee_rate"] == "0.01"
    assert schedule["transaction_limit"] == "5000"

    tm.subscribe_premium(alice, 1)
    schedule = tm.get_subscription_status(alice)
    assert schedule["tier"] == "premium"
    assert schedule["transfer_fee_rate"] == "0.00"
    assert schedule["transaction_limit"] == "50000"


def test_premium_users_listing(verified_user):
    alice, um, tm = verified_user
    assert um.list_premium_users() == {}
    tm.subscribe_premium(alice, 1)
    assert alice in um.list_premium_users()
