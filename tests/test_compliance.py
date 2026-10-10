"""Compliance tests: KYC gating and AML flagging."""

from decimal import Decimal


def _register(um, phone, name, verified=True, risk_tier="standard"):
    success, msg = um.register(phone, name, "1234", "q", "a")
    assert success, msg
    if verified:
        um.submit_kyc(phone, "passport", "XX1234567")
    if risk_tier != "standard":
        um.update_user(phone, risk_tier=risk_tier)


def test_kyc_block(managers):
    um, tm = managers
    _register(um, "+2348011111111", "Unverified", verified=False)
    _register(um, "+2348022222222", "Receiver")
    tm.deposit("+2348022222222", 1000.0)

    success, msg = tm.transfer("+2348011111111", "+2348022222222", 100.0)
    assert not success
    assert "KYC Not Verified" in msg


def test_suspended_account_blocked(managers):
    um, tm = managers
    _register(um, "+2348011111111", "Suspended")
    _register(um, "+2348022222222", "Receiver")
    tm.deposit("+2348011111111", 1000.0)
    um.suspend_user("+2348011111111")

    success, msg = tm.transfer("+2348011111111", "+2348022222222", 100.0)
    assert not success
    assert "suspended" in msg.lower()


def test_aml_flagging_large_amount(managers):
    um, tm = managers
    _register(um, "+2348011111111", "Sender", risk_tier="high")  # high tier: $50k base x10 limit
    _register(um, "+2348022222222", "Receiver", risk_tier="high")
    tm.deposit("+2348011111111", 20000.0)

    success, msg = tm.transfer("+2348011111111", "+2348022222222", 15000.0)
    assert success

    txns = tm.get_history("+2348011111111")
    transfer = next(t for t in txns if t.type == "TRANSFER")
    assert transfer.flagged
    assert "Large amount" in transfer.flag_reason


def test_aml_flagging_velocity(managers):
    um, tm = managers
    _register(um, "+2348011111111", "Sender")
    _register(um, "+2348022222222", "Receiver")
    tm.deposit("+2348011111111", 5000.0)

    # 5 rapid transfers fill the velocity window (>= 5 txns in 5 minutes)
    for _ in range(5):
        success, _ = tm.transfer("+2348011111111", "+2348022222222", 10.0)
        assert success

    success, msg = tm.transfer("+2348011111111", "+2348022222222", 10.0)
    assert success

    txns = tm.get_history("+2348011111111")
    transfer = next(t for t in txns if t.type == "TRANSFER")
    assert transfer.flagged
    assert "Velocity" in transfer.flag_reason


def test_standard_tier_limit_enforced(managers):
    um, tm = managers
    _register(um, "+2348011111111", "Sender")
    _register(um, "+2348022222222", "Receiver", risk_tier="high")
    um.update_user("+2348011111111", balance=Decimal("100000"))

    # standard risk tier: $5,000 base x 10 = $50,000 universal limit
    success, msg = tm.transfer("+2348011111111", "+2348022222222", 60000.0)
    assert not success
    assert "limit" in msg.lower()
