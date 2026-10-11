"""Tier 4 integrations: TransactionManager event hook.

Delivery is asynchronous (background dispatcher thread), so tests drain the
queue with ``tm.dispatcher.wait_idle()`` before asserting.
"""

import time


def test_transfer_emits_event_with_payload(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    events = []
    tm.event_listeners.append(lambda event, payload: events.append((event, payload)))
    ok, msg = tm.transfer(phone, bob_phone, 42, "event test")
    assert ok, msg
    assert tm.dispatcher.wait_idle()
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
    assert tm.dispatcher.wait_idle()
    assert events == ["DEPOSIT", "WITHDRAWAL", "TRANSFER", "BILL_PAYMENT", "REQUEST"]


def test_broken_listener_never_breaks_transaction(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user

    def bad_listener(event, payload):
        raise RuntimeError("listener exploded")

    tm.event_listeners.append(bad_listener)
    ok, msg = tm.transfer(phone, bob_phone, 10, "still works")
    assert ok, msg
    assert tm.dispatcher.wait_idle()
    assert um.get_user(bob_phone).balance == 10


def test_no_listeners_is_noop(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    assert tm.event_listeners == []
    ok, msg = tm.transfer(phone, bob_phone, 10)
    assert ok, msg


def test_dispatch_is_asynchronous(managers, verified_user, second_verified_user):
    """A slow listener must not delay the transaction itself."""
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    done = []

    def slow_listener(event, payload):
        time.sleep(0.5)
        done.append(event)

    tm.event_listeners.append(slow_listener)
    start = time.monotonic()
    ok, _msg = tm.transfer(phone, bob_phone, 10, "async")
    elapsed = time.monotonic() - start
    assert ok
    assert elapsed < 0.4  # the transfer returned before the slow listener finished
    assert tm.dispatcher.wait_idle()
    assert done == ["TRANSFER"]


def test_sync_mode_delivers_inline(managers, verified_user, second_verified_user):
    """Sync mode runs listeners inline (deterministic, no worker thread)."""
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    tm.dispatcher.async_dispatch = False
    events = []
    tm.event_listeners.append(lambda event, payload: events.append(event))
    ok, _msg = tm.transfer(phone, bob_phone, 10, "sync")
    assert ok
    assert events == ["TRANSFER"]  # already delivered — no wait_idle needed
