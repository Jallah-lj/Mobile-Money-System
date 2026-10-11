"""Tier 1 security pack: end-to-end 2FA login flow + server-side session creation.

AppTest runs app.py as a script, so it uses the TOP-LEVEL modules — patch the
top-level ``database`` module's DB_PATH (same pattern as the live-DB AppTests).
"""

import os
import sys

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system", "app.py"))
PHONE = "+2348012345678"
PIN = "1234"


def _patch_db(tmp_path, monkeypatch):
    """Point the TOP-LEVEL database module (the one app.py uses when run as a
    script) at a fresh tmp DB. The sys.path insert happens here, inside the
    test, so collecting this module never pollutes other test files."""
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system")))
    import database as top_database
    db_file = str(tmp_path / "apptest_2fa.db")
    monkeypatch.setattr(top_database, "DB_PATH", db_file)
    return db_file


def _register_user():
    from users import UserManager
    um = UserManager()
    ok, msg = um.register(PHONE, "Alice", PIN, "q", "a")
    assert ok, msg
    return um


def _fill_login_form(at, phone=PHONE, pin=PIN):
    phone_input = [ti for ti in at.text_input if ti.label == "Phone Number"][0]
    pin_input = [ti for ti in at.text_input if ti.label == "PIN"][0]
    phone_input.set_value(phone)
    pin_input.set_value(pin)
    login_btn = [b for b in at.button if b.label == "Login"][0]
    login_btn.click()


def test_2fa_login_requires_otp_and_creates_session(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_user()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    _fill_login_form(at)
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # After correct PIN the user must pass the OTP stage before being logged in
    assert at.session_state["login_stage"] == "otp"
    assert at.session_state.get("current_user_phone") is None

    # Wrong code is rejected
    otp_input = at.text_input(key="otp_input_field")
    otp_input.set_value("000000")
    verify_btn = [b for b in at.button if b.label == "Verify"][0]
    verify_btn.click()
    at.run()
    assert at.session_state.get("current_user_phone") is None

    # Correct code logs the user in and creates a server-side session
    code = at.session_state["generated_code"]
    at.text_input(key="otp_input_field").set_value(code)
    [b for b in at.button if b.label == "Verify"][0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["current_user_phone"] == PHONE

    from sessions import SessionManager
    sm = SessionManager()
    token = at.session_state["session_token"]
    assert sm.is_session_valid(token, PHONE)


def test_2fa_disabled_logs_in_without_otp(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    um = _register_user()
    ok, msg = um.set_two_factor(PHONE, False)
    assert ok, msg

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    _fill_login_form(at)
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # No OTP stage — straight into the app, with a session record
    assert at.session_state.get("login_stage") != "otp"
    assert at.session_state["current_user_phone"] == PHONE

    from sessions import SessionManager
    sm = SessionManager()
    assert sm.is_session_valid(at.session_state["session_token"], PHONE)


def test_revoked_session_forces_logout(tmp_path, monkeypatch):
    """A session revoked server-side (e.g. 'Log Out Everywhere Else') ends the login."""
    _patch_db(tmp_path, monkeypatch)
    _register_user()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    # Seed a logged-in session the way the app expects after login
    at.session_state["current_user_phone"] = PHONE
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["current_user_phone"] == PHONE
    token = at.session_state["session_token"]

    from sessions import SessionManager
    sm = SessionManager()
    assert sm.is_session_valid(token, PHONE)

    # Revoke it out-of-band (another device / admin action)
    sm.revoke(token)

    at.run()
    assert not at.exception, [e.value for e in at.exception]
    # The app detected the dead session and logged the user out
    assert at.session_state.get("current_user_phone") is None
    # ...and tells the user why (the notice flag itself is consumed on render)
    assert any("expired" in w.value.lower() for w in at.warning)


def test_logout_revokes_session(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_user()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = PHONE
    at.run()
    token = at.session_state["session_token"]

    from sessions import SessionManager
    sm = SessionManager()
    assert sm.is_session_valid(token, PHONE)

    # Log out via the sidebar button
    logout_btn = [b for b in at.button if b.label == "Logout"][0]
    logout_btn.click()
    at.run()

    assert at.session_state.get("current_user_phone") is None
    assert not sm.is_session_valid(token, PHONE)
