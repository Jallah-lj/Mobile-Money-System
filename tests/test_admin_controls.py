"""Admin controls: operator fee config, AML rules, billers, admin-initiated deletion."""

from decimal import Decimal

from mobile_money_system.audit import get_audit_logs
from mobile_money_system.billers import BillerManager
from mobile_money_system.config import get_decimal, get_setting, set_setting
from mobile_money_system.privacy import PrivacyManager, pseudonymize
from mobile_money_system.tickets import TicketManager


def test_fee_config_changes_charges(managers, verified_user, second_verified_user):
    """Operator fee settings actually drive the charged fees."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user

    # Default: 0% transfer fee
    ok, _ = tm.transfer(alice, bob, 100)
    assert ok
    assert um.get_user(alice).balance == Decimal("10000") - 100

    # Operator sets a 1% transfer fee
    set_setting("transfer_fee_rate", "0.01")
    ok, _ = tm.transfer(alice, bob, 100)
    assert ok
    assert um.get_user(alice).balance == Decimal("10000") - 100 - 101  # 100 + 1% fee

    # Withdrawal fee config
    set_setting("withdrawal_fee_rate", "0.01")
    ok, _ = tm.withdraw(alice, 100)
    assert ok
    expected_fee = Decimal("100") * Decimal("0.01")
    assert um.get_user(alice).balance == Decimal("10000") - 201 - 100 - expected_fee

    # Bill fee config: pay 100 + $1.00 flat fee = 101
    set_setting("bill_fee_flat", "1.00")
    ok, _ = tm.pay_bill(alice, 100, "Water", "ACC-1")
    assert ok
    assert um.get_user(alice).balance == Decimal("10000") - 100 - 101 - 101 - 101


def test_fee_config_defaults_are_free(managers):
    """The platform defaults to free: 0% transfer, 0.5% withdrawal, $0.25 bill."""
    assert get_decimal("transfer_fee_rate") == Decimal("0.00")
    assert get_decimal("withdrawal_fee_rate") == Decimal("0.005")
    assert get_decimal("bill_fee_flat") == Decimal("0.25")


def test_aml_thresholds_are_configurable(managers, verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user

    # Default threshold is 10k: a 500 transfer is NOT flagged
    ok, _ = tm.transfer(alice, bob, 500)
    assert ok
    assert not [t for t in TicketManager().all_tickets() if t["phone"] == "SYSTEM"]

    # Operator lowers the threshold to 100: the same transfer IS flagged
    set_setting("aml_large_amount_threshold", "100")
    ok, _ = tm.transfer(alice, bob, 500)
    assert ok
    tickets = [t for t in TicketManager().all_tickets(category="security") if t["phone"] == "SYSTEM"]
    assert len(tickets) == 1
    assert tickets[0]["priority"] == "high"


def test_biller_crud(managers):
    bm = BillerManager()
    ok, msg = bm.add("LEC Power", "Electricity (Prepaid)", "MTR-", "0.5% service fee")
    assert ok, msg
    ok, _ = bm.add("", "Water Utility", "X")  # missing name
    assert not ok

    billers = bm.list()
    assert len(billers) == 1
    assert billers[0]["name"] == "LEC Power"

    ok, _ = bm.deactivate(billers[0]["id"])
    assert ok
    assert bm.list() == []  # active_only by default
    assert len(bm.list(active_only=False)) == 1

    ok, _ = bm.remove(billers[0]["id"])
    assert ok
    assert bm.list(active_only=False) == []
    ok, _ = bm.remove(999)
    assert not ok


def test_admin_delete_user(managers, verified_user, second_verified_user):
    """Admin-initiated deletion: personal data gone, financial records pseudonymized."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.transfer(alice, bob, 25, "keep a record")

    pm = PrivacyManager()
    ok, msg = pm.admin_delete_user(alice, "0000000000", "fraud")
    assert ok, msg

    # Account gone
    assert um.get_user(alice) is None
    # Financial records retained but pseudonymized
    pseudo = pseudonymize(alice)
    txns = tm.get_history(bob)
    assert any(t.sender_phone == pseudo for t in txns)
    # Audit trail records the admin action
    logs = get_audit_logs(limit=50, action="ADMIN_DELETE_USER")
    assert len(logs) == 1
    assert logs[0].actor_phone == "0000000000"

    # Unknown user rejected
    ok, _ = pm.admin_delete_user("+2349999999999", "0000000000")
    assert not ok


def test_get_setting_reads_overrides(managers):
    assert get_setting("aml_velocity_count") == "5"  # default
    set_setting("aml_velocity_count", "9")
    assert get_setting("aml_velocity_count") == "9"
