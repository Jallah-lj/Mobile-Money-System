"""Tier 4 integrations: TransactionManager event hook."""


def test_transfer_emits_event_with_payload(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    events = []
    tm.event_listeners.append(lambda event, payload: events.append((event, payload)))
    ok, msg = tm.transfer(phone, bob_phone, 42, "event test")
    assert ok, msg
    assert len(events) == 1
    event, payload = events[0]
    assert event == "TRANSFER"
    assert payload["sender_phone"] == phone
    assert payload["receiver_phone"] == bob_phone
    assert payload["amount"] == "42.0000" or float(payload["amount"]) == 42.0
    assert payload["type"] == "TRANSFER"


def test_all_money_movements_emit(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    events = []
    tm.event_listeners.append(lambda event, payload: events.append(event))
    tm.deposit(phone, 100)
    tm.withdraw(phone, 10)
    tm.transfer(phone, bob_phone, 5)
    tm.pay_bill(phone, 5, "LEC", "MTR-1")
    tm.request_money(bob_phone, phone, 7)
    assert events == ["DEPOSIT", "WITHDRAWAL", "TRANSFER", "BILL_PAYMENT", "REQUEST"]


def test_broken_listener_never_breaks_transaction(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user

    def bad_listener(event, payload):
        raise RuntimeError("listener exploded")

    tm.event_listeners.append(bad_listener)
    ok, msg = tm.transfer(phone, bob_phone, 10, "still works")
    assert ok, msg
    assert um.get_user(bob_phone).balance == 10


def test_no_listeners_is_noop(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    assert tm.event_listeners == []
    ok, msg = tm.transfer(phone, bob_phone, 10)
    assert ok, msg
