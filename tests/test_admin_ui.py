"""Admin controls UI: impersonation round-trip, real HARD DELETE, fee config panel.

AppTest runs app.py as a script, so it uses the TOP-LEVEL modules — patch the
top-level ``database`` module's DB_PATH (same pattern as test_privacy_ui).
"""

import os
import sys

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system", "app.py"))
ADMIN_PHONE = "+2348099999999"
TARGET_PHONE = "+2348012345678"


def _patch_db(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system")))
    import database as top_database
    monkeypatch.setattr(top_database, "DB_PATH", str(tmp_path / "apptest_admin.db"))


def _register_admin_and_target():
    from database import get_db
    from users import UserManager
    um = UserManager()
    ok, msg = um.register(ADMIN_PHONE, "Admin", "admin123", "q", "a")
    assert ok, msg
    ok, msg = um.register(TARGET_PHONE, "Alice", "1234", "q", "a")
    assert ok, msg
    with get_db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (ADMIN_PHONE,))
        conn.commit()
    return um


def _boot_admin(at):
    at.session_state["current_user_phone"] = ADMIN_PHONE
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _select_target(at):
    sb = [s for s in at.selectbox if s.label == "Select Target User"][0]
    sb.set_value(TARGET_PHONE)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_impersonation_round_trip(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_admin_and_target()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    _boot_admin(at)  # admin dashboard, Users tab (default)
    _select_target(at)

    imp_btn = [b for b in at.button if b.label == "Impersonate User"][0]
    imp_btn.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # Now viewing the app AS the target user, with the exit banner visible
    assert at.session_state["impersonator_phone"] == ADMIN_PHONE
    assert at.session_state["current_user_phone"] == TARGET_PHONE
    exit_btns = [b for b in at.button if "EXIT IMPERSONATION" in b.label]
    assert exit_btns

    exit_btns[0].click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    # Back to the admin dashboard as the admin
    assert at.session_state["current_user_phone"] == ADMIN_PHONE
    assert "impersonator_phone" not in at.session_state

    # The impersonation is audited
    from audit import get_audit_logs
    actions = [e.action for e in get_audit_logs(limit=50)]
    assert "IMPERSONATE_START" in actions
    assert "IMPERSONATE_STOP" in actions


def test_hard_delete_really_deletes(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    um = _register_admin_and_target()
    assert um.get_user(TARGET_PHONE) is not None

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    _boot_admin(at)
    _select_target(at)

    # Without the confirmation checkbox the delete is refused
    del_btn = [b for b in at.button if b.label == "HARD DELETE"][0]
    del_btn.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert um.get_user(TARGET_PHONE) is not None

    # Tick the confirmation, then delete for real
    cb = [c for c in at.checkbox if c.key == f"hard_del_confirm_{TARGET_PHONE}"][0]
    cb.set_value(True)
    del_btn = [b for b in at.button if b.label == "HARD DELETE"][0]
    del_btn.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert um.get_user(TARGET_PHONE) is None

    from audit import get_audit_logs
    assert any(e.action == "ADMIN_DELETE_USER" for e in get_audit_logs(limit=50))


def test_system_tab_fee_config_saves(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    _register_admin_and_target()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = ADMIN_PHONE
    at.session_state["admin_nav"] = "System"
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # The real fee panel renders with the current (free) defaults
    fee_inputs = {ni.key: ni for ni in at.number_input}
    assert "cfg_transfer_fee" in fee_inputs
    assert "cfg_withdrawal_fee" in fee_inputs
    assert "cfg_bill_fee" in fee_inputs
    assert float(fee_inputs["cfg_transfer_fee"].value) == 0.0
    assert float(fee_inputs["cfg_withdrawal_fee"].value) == 0.005
    assert float(fee_inputs["cfg_bill_fee"].value) == 0.25

    # Change the transfer fee and save
    fee_inputs["cfg_transfer_fee"].set_value(0.01)
    save_btn = [b for b in at.button if b.label == "Save System Config"][0]
    save_btn.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    from config import get_setting
    assert get_setting("transfer_fee_rate") == "0.01"
