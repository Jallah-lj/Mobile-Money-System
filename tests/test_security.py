"""Security hardening tests: lockout, OTP, audit trail, fresh-DB bootstrap."""

import os

from mobile_money_system import database
from mobile_money_system.audit import get_audit_logs
from mobile_money_system.users import (
    LOCKOUT_DURATION_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    UserManager,
)


def test_login_lockout_after_max_attempts(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    for _ in range(MAX_LOGIN_ATTEMPTS):
        assert um.login("+2348012345678", "0000") is None

    locked, remaining = um.is_locked_out("+2348012345678")
    assert locked
    assert 0 < remaining <= LOCKOUT_DURATION_SECONDS

    # Even the CORRECT pin is rejected while locked out
    assert um.login("+2348012345678", "1234") is None


def test_successful_login_clears_failures(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        um.login("+2348012345678", "0000")
    assert not um.is_locked_out("+2348012345678")[0]

    assert um.login("+2348012345678", "1234") is not None

    # Failure counter was reset: a fresh batch of failures starts from zero
    for _ in range(MAX_LOGIN_ATTEMPTS - 1):
        um.login("+2348012345678", "0000")
    assert not um.is_locked_out("+2348012345678")[0]


def test_lockout_expires(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    for _ in range(MAX_LOGIN_ATTEMPTS):
        um.login("+2348012345678", "0000")
    assert um.is_locked_out("+2348012345678")[0]

    # Simulate the lockout having expired (DB-backed state)
    from mobile_money_system.database import get_db
    with get_db() as conn:
        conn.execute("UPDATE account_lockouts SET locked_until = 0 WHERE phone = ?",
                     ("+2348012345678",))
        conn.commit()
    assert not um.is_locked_out("+2348012345678")[0]
    assert um.login("+2348012345678", "1234") is not None


def test_lockout_survives_new_manager_instance(db_path):
    """Lockouts are DB-backed: a fresh manager (e.g. after a restart) still sees them."""
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    for _ in range(MAX_LOGIN_ATTEMPTS):
        um.login("+2348012345678", "0000")
    assert um.is_locked_out("+2348012345678")[0]

    um2 = UserManager()  # simulates a process restart
    locked, _ = um2.is_locked_out("+2348012345678")
    assert locked
    assert um2.login("+2348012345678", "1234") is None  # still blocked


def test_otp_survives_new_manager_instance(db_path):
    """OTPs are DB-backed: a fresh manager can verify a code issued by another."""
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    code = um.generate_otp("+2348012345678")

    um2 = UserManager()  # simulates a process restart
    assert um2.verify_otp("+2348012345678", code) is True
    assert um2.verify_otp("+2348012345678", code) is False  # still single-use


def test_otp_backdoor_removed(db_path):
    """The old hardcoded '123456' master code must no longer authenticate."""
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    assert um.verify_otp("+2348012345678", "123456") is False


def test_otp_roundtrip(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    code = um.generate_otp("+2348012345678")
    assert um.verify_otp("+2348012345678", "000000") is False  # wrong code
    assert um.verify_otp("+2348012345678", code) is True       # right code
    assert um.verify_otp("+2348012345678", code) is False      # single-use


def test_audit_log_records_auth_events(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    um.login("+2348012345678", "1234")
    um.login("+2348012345678", "9999")

    logs = get_audit_logs(limit=50)
    actions = [e.action for e in logs]
    assert "REGISTER" in actions
    assert "LOGIN_SUCCESS" in actions
    assert "LOGIN_FAILURE" in actions

    failure = next(e for e in logs if e.action == "LOGIN_FAILURE")
    assert failure.status == "FAILURE"


def test_audit_log_records_transactions(verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.transfer(alice, bob, 25.0, "audit me")

    logs = get_audit_logs(limit=50, action="TRANSFER")
    assert len(logs) == 1
    assert logs[0].actor_phone == alice
    assert "audit me" in logs[0].details


def test_audit_log_records_deposits(verified_user):
    alice, um, tm = verified_user
    tm.deposit(alice, 100.0)

    logs = get_audit_logs(limit=50, action="DEPOSIT")
    assert len(logs) == 1
    assert logs[0].actor_phone == alice


def test_fresh_database_bootstraps_itself(tmp_path, monkeypatch):
    """UserManager must auto-create the schema on a brand-new database file."""
    path = str(tmp_path / "brand_new.db")
    assert not os.path.exists(path)
    monkeypatch.setattr(database, "DB_PATH", path)

    um = UserManager()  # must not raise
    admin = um.get_user("0000000000")
    assert admin is not None
    assert admin.role == "admin"


def test_default_admin_can_login(tmp_path, monkeypatch):
    path = str(tmp_path / "brand_new.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    um = UserManager()
    admin = um.login("0000000000", "admin123")
    assert admin is not None
    assert admin.role == "admin"
