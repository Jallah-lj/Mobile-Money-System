"""Packaging & compliance: AML flags auto-open admin tickets."""

from mobile_money_system.tickets import TicketManager


def _aml_tickets():
    return [t for t in TicketManager().all_tickets(category="security")
            if t["phone"] == "SYSTEM"]


def test_large_transaction_creates_aml_ticket(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    assert _aml_tickets() == []

    # >= 10k triggers the large-amount AML rule
    ok, msg = tm.transfer(phone, bob_phone, 10000, "big transfer")
    assert ok, msg

    tickets = _aml_tickets()
    assert len(tickets) == 1
    t = tickets[0]
    assert t["priority"] == "high"
    assert "AML flag" in t["subject"]
    assert "Large amount" in t["message"]


def test_velocity_creates_aml_ticket(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user

    # 5 transfers inside the velocity window, then the 6th gets flagged
    for _ in range(5):
        ok, _ = tm.transfer(phone, bob_phone, 10, "rapid")
        assert ok
    assert _aml_tickets() == []
    ok, _ = tm.transfer(phone, bob_phone, 10, "rapid 6")
    assert ok

    tickets = _aml_tickets()
    assert len(tickets) == 1
    assert "Rapid movement" in tickets[0]["message"]


def test_normal_transactions_create_no_tickets(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    ok, _ = tm.transfer(phone, bob_phone, 100, "normal")
    assert ok
    tm.withdraw(phone, 50, "atm")
    assert _aml_tickets() == []


def test_aml_ticket_references_transaction(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    tm.transfer(phone, bob_phone, 10000, "traceable")
    txn = [t for t in tm.get_history(phone) if float(t.amount) == 10000][0]
    tickets = _aml_tickets()
    assert txn.id in tickets[0]["message"]
