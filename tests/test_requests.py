"""Money request (request-to-pay) cycle tests."""

from decimal import Decimal


def test_request_cycle_pay(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.deposit(bob, 1000.0)

    success, msg = tm.request_money(alice, bob, 50.0, "Lunch")
    assert success, msg

    pending = [t for t in tm.get_history(alice)
               if t.type == "REQUEST" and t.status == "PENDING"]
    assert len(pending) == 1
    req_id = pending[0].id

    alice_before = um.get_user(alice).balance
    success, msg = tm.process_request(req_id, "PAY")
    assert success, msg

    # Bob (free tier) pays 50 + 1% fee = 50.50
    assert um.get_user(bob).balance == Decimal("1000.0") - Decimal("50.5")
    # Alice received exactly 50
    assert um.get_user(alice).balance == alice_before + Decimal("50.0")

    assert tm.get_transaction(req_id).status == "COMPLETED"


def test_request_cycle_decline(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.deposit(bob, 1000.0)
    bob_before = um.get_user(bob).balance

    tm.request_money(alice, bob, 50.0, "Lunch")
    req_id = [t for t in tm.get_history(alice)
              if t.type == "REQUEST" and t.status == "PENDING"][0].id

    success, msg = tm.process_request(req_id, "DECLINE")
    assert success, msg
    assert tm.get_transaction(req_id).status == "DECLINED"
    assert um.get_user(bob).balance == bob_before  # no money moved


def test_request_unknown_users(managers):
    um, tm = managers
    success, msg = tm.request_money("+2340000000001", "+2340000000002", 10.0)
    assert not success
    assert "not found" in msg.lower()
