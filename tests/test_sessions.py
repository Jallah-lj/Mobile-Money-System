"""Tier 1 security pack: server-side sessions, 2FA toggle, step-up threshold."""

import time

from mobile_money_system import database
from mobile_money_system.sessions import SessionManager
from mobile_money_system.users import UserManager, HIGH_VALUE_STEPUP_THRESHOLD


def test_session_lifecycle(db_path):
    sm = SessionManager()
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    token = sm.create_session("+2348012345678", provider="web", user_agent="pytest")
    assert token
    assert sm.is_session_valid(token, "+2348012345678")

    # Touch updates last_seen
    sess = sm.get_session(token)
    time.sleep(0.01)
    sm.touch(token)
    assert sm.get_session(token)["last_seen"] >= sess["last_seen"]

    # Revoke ends validity
    assert sm.revoke(token) is True
    assert not sm.is_session_valid(token, "+2348012345678")
    assert sm.get_session(token)["active"] == 0
    # Revoking twice is a no-op
    assert sm.revoke(token) is False


def test_session_belongs_to_owner(db_path):
    sm = SessionManager()
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    um.register("+2348087654321", "Bob", "1234", "q", "a")

    token = sm.create_session("+2348012345678")
    # A session is only valid for its owner
    assert not sm.is_session_valid(token, "+2348087654321")
    # Unknown tokens are invalid
    assert not sm.is_session_valid("deadbeef", "+2348012345678")


def test_revoke_all_keeps_current_session(db_path):
    sm = SessionManager()
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    t1 = sm.create_session("+2348012345678", user_agent="phone")
    t2 = sm.create_session("+2348012345678", user_agent="laptop")
    t3 = sm.create_session("+2348012345678", user_agent="tablet")

    revoked = sm.revoke_all("+2348012345678", except_token=t2)
    assert revoked == 2
    assert not sm.is_session_valid(t1, "+2348012345678")
    assert sm.is_session_valid(t2, "+2348012345678")
    assert not sm.is_session_valid(t3, "+2348012345678")

    active = sm.list_active("+2348012345678")
    assert [s["token"] for s in active] == [t2]


def test_list_active_excludes_revoked(db_path):
    sm = SessionManager()
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    t1 = sm.create_session("+2348012345678")
    sm.create_session("+2348012345678")
    sm.revoke(t1)
    assert len(sm.list_active("+2348012345678")) == 1


def test_two_factor_default_enabled_and_toggle(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    # 2FA is on by default (matches the OTP login flow)
    assert um.get_user("+2348012345678").two_factor_enabled is True

    ok, msg = um.set_two_factor("+2348012345678", False)
    assert ok, msg
    assert um.get_user("+2348012345678").two_factor_enabled is False

    ok, msg = um.set_two_factor("+2348012345678", True)
    assert ok, msg
    assert um.get_user("+2348012345678").two_factor_enabled is True

    # Unknown user
    ok, msg = um.set_two_factor("+2349999999999", True)
    assert not ok


def test_two_factor_via_update_user(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    ok, _ = um.update_user("+2348012345678", two_factor_enabled=False)
    assert ok
    assert um.get_user("+2348012345678").two_factor_enabled is False


def test_two_factor_in_public_dict(db_path):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    public = um.get_user("+2348012345678").to_public_dict()
    assert public["two_factor_enabled"] is True
    assert "pin" not in public and "sec_a" not in public


def test_stepup_threshold_constant():
    # High-value debits above this amount require a fresh OTP
    assert HIGH_VALUE_STEPUP_THRESHOLD == 1000


def test_existing_users_get_two_factor_column(db_path):
    """The migration adds two_factor_enabled=1 to users created before the column."""
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT two_factor_enabled FROM users WHERE phone = ?", ("+2348012345678",))
        assert cursor.fetchone()[0] == 1
