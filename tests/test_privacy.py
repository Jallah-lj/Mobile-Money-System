"""Packaging & compliance: privacy data controls (export + deletion flow)."""

from mobile_money_system.privacy import PrivacyManager, export_to_csv, pseudonymize
from mobile_money_system.tickets import TicketManager


def test_export_contains_all_sections_and_hides_credentials(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    tm.transfer(phone, bob_phone, 25, "export test")

    pm = PrivacyManager()
    data = pm.export_user_data(phone)
    assert data is not None
    for section in ("profile", "transactions", "beneficiaries", "scheduled_payments",
                    "tickets", "notification_channels", "sessions", "audit_trail"):
        assert section in data, section
    assert data["profile"]["phone"] == phone
    assert "pin" not in data["profile"]
    assert "sec_a" not in data["profile"]
    assert any(t["id"] for t in data["transactions"])


def test_export_unknown_user_returns_none(db_path):
    assert PrivacyManager().export_user_data("+2349999999999") is None


def test_deletion_request_flow(db_path):
    pm = PrivacyManager()
    from mobile_money_system.users import UserManager
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    ok, msg = pm.request_deletion("+2348012345678", "moving abroad")
    assert ok, msg
    # Duplicate pending request rejected
    ok, _ = pm.request_deletion("+2348012345678", "again")
    assert not ok
    # Unknown user
    ok, _ = pm.request_deletion("+2349999999999")
    assert not ok

    pending = pm.pending_deletions()
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    assert pm.my_deletion_requests("+2348012345678")[0]["reason"] == "moving abroad"


def test_cancel_own_pending_request(db_path):
    pm = PrivacyManager()
    from mobile_money_system.users import UserManager
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    pm.request_deletion("+2348012345678")
    rid = pm.pending_deletions()[0]["id"]
    assert pm.cancel_deletion_request("+2348012345678", rid) is True
    assert pm.pending_deletions() == []
    # Cannot cancel someone else's / already-handled request
    assert pm.cancel_deletion_request("+2348012345678", rid) is False


def test_reject_deletion(db_path):
    pm = PrivacyManager()
    from mobile_money_system.users import UserManager
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    pm.request_deletion("+2348012345678")
    rid = pm.pending_deletions()[0]["id"]

    ok, msg = pm.reject_deletion(rid, "0000000000", "please keep your account")
    assert ok, msg
    req = pm.get_request(rid)
    assert req["status"] == "rejected"
    assert req["reviewed_by"] == "0000000000"
    assert req["review_note"] == "please keep your account"
    # Account untouched
    assert um.get_user("+2348012345678") is not None
    # Double review rejected
    ok, _ = pm.reject_deletion(rid, "0000000000")
    assert not ok


def test_approve_deletion_pseudonymizes_records(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    tm.transfer(phone, bob_phone, 25, "keep a record")
    from mobile_money_system.beneficiaries import BeneficiaryManager
    BeneficiaryManager(um).add(phone, bob_phone, "Bob")
    TicketManager().create(phone, "help", "account", "please delete me")

    pm = PrivacyManager()
    ok, _ = pm.request_deletion(phone, "gdpr")
    assert ok
    rid = pm.pending_deletions()[0]["id"]

    ok, msg = pm.approve_deletion(rid, "0000000000")
    assert ok, msg

    # Account gone
    assert um.get_user(phone) is None
    # Request closed
    assert pm.get_request(rid)["status"] == "approved"

    # Financial records retained but pseudonymized
    pseudo = pseudonymize(phone)
    assert pseudo.startswith("DELETED-")
    assert pseudonymize(phone) == pseudo  # stable
    txns = tm.get_history(bob_phone)
    assert any(t.sender_phone == pseudo for t in txns)
    assert all(t.sender_phone != phone for t in txns)

    from mobile_money_system.audit import get_audit_logs
    assert all(e.actor_phone != phone for e in get_audit_logs(limit=1000))

    # Personal data deleted outright
    from mobile_money_system.database import get_db
    with get_db() as conn:
        cursor = conn.cursor()
        for table, col in (("beneficiaries", "owner_phone"), ("tickets", "phone"),
                           ("sessions", "phone"), ("notification_channels", "phone")):
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (phone,))
            assert cursor.fetchone()[0] == 0, table


def test_export_to_csv_has_sections(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    tm.transfer(phone, bob_phone, 10, "csv test")
    data = PrivacyManager().export_user_data(phone)
    csv_text = export_to_csv(data)
    assert "# PROFILE" in csv_text
    assert "# TRANSACTIONS" in csv_text
    assert "csv test" in csv_text
