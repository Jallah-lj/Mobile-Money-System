"""Tier 2 money features: saved beneficiaries."""

from mobile_money_system.beneficiaries import BeneficiaryManager


def test_add_and_list_beneficiary(managers, verified_user):
    phone, um, tm = verified_user
    bm = BeneficiaryManager(um)
    ok, msg = bm.add(phone, "+2348087654321", "Bob")
    assert ok, msg
    bens = bm.list(phone)
    assert len(bens) == 1
    assert bens[0]["nickname"] == "Bob"
    assert bens[0]["phone"] == "+2348087654321"
    # Bob is not registered in this DB -> flagged as unregistered
    assert bens[0]["is_registered"] is False


def test_add_defaults_nickname_to_recipient_name(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    bm = BeneficiaryManager(um)
    ok, msg = bm.add(phone, bob_phone)  # no nickname
    assert ok, msg
    bens = bm.list(phone)
    assert bens[0]["nickname"] == "Bob"
    assert bens[0]["is_registered"] is True
    assert bens[0]["recipient_name"] == "Bob"


def test_add_rejects_invalid_phone_and_self(managers, verified_user):
    phone, um, tm = verified_user
    bm = BeneficiaryManager(um)
    ok, _ = bm.add(phone, "not-a-phone", "X")
    assert not ok
    ok, _ = bm.add(phone, phone, "Myself")
    assert not ok


def test_duplicate_add_updates_nickname(managers, verified_user):
    phone, um, tm = verified_user
    bm = BeneficiaryManager(um)
    bm.add(phone, "+2348087654321", "Bobby")
    ok, msg = bm.add(phone, "+2348087654321", "Robert")
    assert ok, msg
    bens = bm.list(phone)
    assert len(bens) == 1
    assert bens[0]["nickname"] == "Robert"


def test_remove_and_rename(managers, verified_user):
    phone, um, tm = verified_user
    bm = BeneficiaryManager(um)
    bm.add(phone, "+2348087654321", "Bob")
    ok, msg = bm.rename(phone, "+2348087654321", "Bobby")
    assert ok, msg
    assert bm.get(phone, "+2348087654321")["nickname"] == "Bobby"
    assert bm.remove(phone, "+2348087654321") is True
    assert bm.list(phone) == []
    assert bm.remove(phone, "+2348087654321") is False
    ok, _ = bm.rename(phone, "+2348087654321", "X")
    assert not ok


def test_touch_updates_last_used_and_orders_list(managers, verified_user):
    phone, um, tm = verified_user
    bm = BeneficiaryManager(um)
    bm.add(phone, "+2348087654321", "Bob")
    bm.add(phone, "+2348099999999", "Alice")
    bm.touch(phone, "+2348087654321")
    bens = bm.list(phone)
    # Most recently used first
    assert bens[0]["phone"] == "+2348087654321"
    assert bens[0]["last_used_at"] is not None


def test_recent_recipients_from_history(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    bm = BeneficiaryManager(um)
    assert bm.recent_recipients(phone) == []
    tm.transfer(phone, bob_phone, 50, "test")
    tm.transfer(phone, bob_phone, 25, "test 2")
    recent = bm.recent_recipients(phone)
    assert recent == [bob_phone]


def test_beneficiaries_are_owner_scoped(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    bm = BeneficiaryManager(um)
    bm.add(phone, "+2348011111111", "A")
    assert bm.list(bob_phone) == []
    assert bm.remove(bob_phone, "+2348011111111") is False
