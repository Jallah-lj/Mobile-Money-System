"""Packaging & compliance: privacy UI smoke tests (Settings export/deletion + admin queue).

AppTest runs app.py as a script, so it uses the TOP-LEVEL modules — patch the
top-level ``database`` module's DB_PATH (same pattern as test_login_2fa_flow).
The nav option_menus have fixed keys (``main_nav``/``admin_nav``), so AppTest can
seed the selected tab via session_state.
"""

import os
import sys

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system", "app.py"))
PHONE = "+2348012345678"
ADMIN_PHONE = "+2348099999999"


def _patch_db(tmp_path, monkeypatch):
    """Point the TOP-LEVEL database module (the one app.py uses when run as a
    script) at a fresh tmp DB. The sys.path insert happens inside the test."""
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system")))
    import database as top_database
    monkeypatch.setattr(top_database, "DB_PATH", str(tmp_path / "apptest_privacy.db"))


def _register_users():
    from database import get_db
    from users import UserManager
    um = UserManager()
    ok, msg = um.register(PHONE, "Alice", "1234", "q", "a")
    assert ok, msg
    ok, msg = um.register(ADMIN_PHONE, "Admin", "admin123", "q", "a")
    assert ok, msg
    # update_user doesn't allow role changes — promote directly (as set_admin.py does)
    with get_db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (ADMIN_PHONE,))
        conn.commit()
    return um


def test_settings_privacy_section_renders(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_users()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = PHONE
    at.session_state["main_nav"] = "Settings"
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    headers = [m.value for m in at.markdown]
    assert any("Privacy & Data" in h for h in headers)
    assert any("Export my data" in h for h in headers)
    assert any("Delete my account" in h for h in headers)
    # Export download buttons are offered
    dl_labels = [b.label for b in at.get("download_button")]
    assert "Download my data (JSON)" in dl_labels
    assert "Download my data (CSV)" in dl_labels
    # No pending deletion request yet -> the request form renders
    assert any(ta.label == "Reason (optional)" for ta in at.text_area)
    assert any("Request Account Deletion" in b.label for b in at.button)


def test_user_can_request_deletion_from_settings(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_users()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = PHONE
    at.session_state["main_nav"] = "Settings"
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # Tick the confirmation checkbox and submit the form
    cb = [c for c in at.checkbox if "understand my account" in c.label][0]
    cb.set_value(True)
    submit = [b for b in at.button if "Request Account Deletion" in b.label][0]
    submit.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    from privacy import PrivacyManager
    pending = PrivacyManager().pending_deletions()
    assert len(pending) == 1 and pending[0]["phone"] == PHONE


def test_admin_sees_pending_deletion_requests(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_users()
    from privacy import PrivacyManager
    ok, _ = PrivacyManager().request_deletion(PHONE, "gdpr request")
    assert ok

    # Admin nav defaults to the Users tab, which holds the deletion queue
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = ADMIN_PHONE
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    headers = [m.value for m in at.markdown]
    assert any("Pending Account Deletion Requests" in h for h in headers)
    expander_labels = [e.label for e in at.expander]
    assert any(PHONE in label for label in expander_labels)
    btn_labels = [b.label for b in at.button]
    assert any("Approve Deletion" in label for label in btn_labels)
    assert any(label == "Reject" for label in btn_labels)
