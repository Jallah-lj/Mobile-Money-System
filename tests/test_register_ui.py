"""Professional Register page: layout, field-level validation, consent, navigation.

AppTest runs app.py as a script, so it uses the TOP-LEVEL modules — patch the
top-level ``database`` module's DB_PATH (same pattern as test_privacy_ui).
"""

import os
import sys

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system", "app.py"))
PHONE = "+2348012345678"

CONSENT_LABEL = "I accept the Terms of Service and the Privacy Policy"


def _patch_db(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system")))
    import database as top_database
    monkeypatch.setattr(top_database, "DB_PATH", str(tmp_path / "apptest_register.db"))


def _open_register():
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["auth_nav"] = "Register"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _set(at, label, value):
    ti = [t for t in at.text_input if t.label == label][0]
    ti.set_value(value)


def _fill_valid_form(at):
    _set(at, "Full name", "Alice")
    _set(at, "Phone Number", PHONE)
    _set(at, "PIN", "1234")
    _set(at, "Your answer", "blue")


def test_register_page_renders_professional_layout(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    at = _open_register()

    # Brand hero panel with headline + trust points
    hero = [m.value for m in at.markdown if 'class="auth-hero"' in m.value]
    assert hero, "hero panel missing"
    assert "Create your account" in hero[0]
    assert "Mobile Money System" in hero[0]
    assert "Bank-grade security with 2FA" in hero[0]

    # Form sections (match the section DIVs, not the stylesheet's .auth-section rules)
    sections = " ".join(m.value for m in at.markdown if "class='auth-section'" in m.value)
    for expected in ("Personal details", "Security", "Preferences", "Terms & privacy"):
        assert expected in sections, f"missing section: {expected}"

    # Widgets: fields, consent checkbox, CTA, sign-in link
    labels = [t.label for t in at.text_input]
    assert "Full name" in labels and "Phone Number" in labels and "PIN" in labels and "Your answer" in labels
    assert any(sb.label == "Security question" for sb in at.selectbox)
    assert any(sb.label == "Preferred currency" for sb in at.selectbox)
    assert any(c.label == CONSENT_LABEL for c in at.checkbox)
    button_labels = [b.label for b in at.button]
    assert "Create account" in button_labels
    assert "Log in" in button_labels

    # Hints render as captions
    captions = [c.value for c in at.caption]
    assert any("international format" in c for c in captions)


def test_register_field_level_validation(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    at = _open_register()

    submit = [b for b in at.button if b.label == "Create account"][0]
    submit.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    errors = [e.value for e in at.error]
    assert "Please enter your full name." in errors
    assert any("Invalid phone number" in e for e in errors)
    assert "Your PIN must be exactly 4 digits." in errors
    assert "Please answer the security question." in errors
    assert any("must accept the Terms of Service" in e for e in errors)

    # No user was created
    from users import UserManager
    assert UserManager().get_user(PHONE) is None


def test_register_success_creates_user_with_consent(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    at = _open_register()
    _fill_valid_form(at)
    cb = [c for c in at.checkbox if c.label == CONSENT_LABEL][0]
    cb.set_value(True)

    submit = [b for b in at.button if b.label == "Create account"][0]
    submit.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    from privacy import PrivacyManager
    from users import UserManager
    user = UserManager().get_user(PHONE)
    assert user is not None and user.name == "Alice"
    pm = PrivacyManager()
    assert pm.has_consent(PHONE, "terms")
    assert pm.has_consent(PHONE, "privacy")
    assert any("Success" in s.value for s in at.success)


def test_register_blocked_without_consent(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    at = _open_register()
    _fill_valid_form(at)  # everything filled EXCEPT the consent checkbox

    submit = [b for b in at.button if b.label == "Create account"][0]
    submit.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    errors = [e.value for e in at.error]
    assert any("must accept the Terms of Service" in e for e in errors)

    from users import UserManager
    assert UserManager().get_user(PHONE) is None


def test_register_login_link_navigates_to_login(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    at = _open_register()

    login_btn = [b for b in at.button if b.label == "Log in"][0]
    login_btn.click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    # The login form is now showing
    button_labels = [b.label for b in at.button]
    assert "Login" in button_labels
    assert any(t.label == "Phone Number" for t in at.text_input)
