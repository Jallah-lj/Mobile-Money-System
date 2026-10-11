"""Phase E: data privacy laws, made real.

Consent ledger (versioned, revocable, recorded at registration), legal document
versioning with re-acceptance prompts, the right to rectification, and the
data breach register — GDPR-style / Rwanda Law No. 058/2021.
"""

import os
import sys

from mobile_money_system.audit import get_audit_logs
from mobile_money_system.database import init_db
from mobile_money_system.privacy import PrivacyManager
from mobile_money_system.users import UserManager

ALICE = "+2348012345678"
ADMIN_PHONE = "+2348099999999"

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system", "app.py"))


# --- PrivacyManager: legal documents + consent ledger --------------------------

def test_legal_documents_seeded_and_idempotent(db_path):
    pm = PrivacyManager()
    policy = pm.get_active_document("privacy_policy")
    terms = pm.get_active_document("terms_of_service")
    assert policy and policy["version"] == "1.0" and "YOUR RIGHTS" in policy["content"]
    assert terms and terms["version"] == "1.0"
    # Re-init must not duplicate documents
    PrivacyManager()
    assert len(pm.list_documents("privacy_policy")) == 1
    assert len(pm.list_documents("terms_of_service")) == 1


def test_legacy_users_get_backfilled_consents(db_path):
    um = UserManager()
    ok, _ = um.register(ALICE, "Alice", "1234", "q", "a")
    assert ok
    pm = PrivacyManager()  # init backfills consents for pre-existing users
    assert pm.has_consent(ALICE, "terms")
    assert pm.has_consent(ALICE, "privacy")
    assert not pm.policy_update_required(ALICE)


def test_consent_record_and_revoke(db_path):
    um = UserManager()
    um.register(ALICE, "Alice", "1234", "q", "a")
    pm = PrivacyManager()

    ok, _ = pm.record_consent(ALICE, "marketing", "opt-in")
    assert ok
    assert pm.has_consent(ALICE, "marketing")

    ok, _ = pm.revoke_consent(ALICE, "marketing")
    assert ok
    assert not pm.has_consent(ALICE, "marketing")
    # The revoked row stays in the ledger for the record
    assert any(c["purpose"] == "marketing" and c["revoked_at"] for c in pm.get_consents(ALICE))

    # Re-consent supersedes the revoked row
    pm.record_consent(ALICE, "marketing", "opt-in")
    active = [c for c in pm.get_consents(ALICE) if c["purpose"] == "marketing" and not c["revoked_at"]]
    assert len(active) == 1

    # Invalid purpose rejected
    ok, msg = pm.record_consent(ALICE, "bogus", "1.0")
    assert not ok
    ok, msg = pm.revoke_consent(ALICE, "bogus")
    assert not ok


def test_policy_update_required_and_reacceptance(db_path):
    um = UserManager()
    um.register(ALICE, "Alice", "1234", "q", "a")
    pm = PrivacyManager()
    assert not pm.policy_update_required(ALICE)

    # Publish a new privacy policy version -> users must re-accept
    ok, _ = pm.publish_document("privacy_policy", "1.1", "Updated policy text...", ADMIN_PHONE)
    assert ok
    assert pm.policy_update_required(ALICE)
    assert pm.get_active_document("privacy_policy")["version"] == "1.1"
    # Old version kept for the record
    assert len(pm.list_documents("privacy_policy")) == 2

    ok, _ = pm.accept_current_policies(ALICE)
    assert ok
    assert not pm.policy_update_required(ALICE)
    assert pm.active_consent(ALICE, "privacy")["policy_version"] == "1.1"

    # Invalid document type rejected
    ok, _ = pm.publish_document("cookie_banner", "1.0", "x", ADMIN_PHONE)
    assert not ok


def test_update_profile_rectification(db_path):
    um = UserManager()
    um.register(ALICE, "Alice", "1234", "q", "a")
    pm = PrivacyManager()

    ok, _ = pm.update_profile(ALICE, "Alice Cooper")
    assert ok
    assert um.get_user(ALICE).name == "Alice Cooper"

    # Empty / over-long names rejected
    ok, _ = pm.update_profile(ALICE, "   ")
    assert not ok
    ok, _ = pm.update_profile(ALICE, "x" * 101)
    assert not ok
    ok, _ = pm.update_profile("+2349999999999", "Ghost")
    assert not ok

    # Audit trail records the rectification
    actions = [e.action for e in get_audit_logs(actor_phone=ALICE)]
    assert "PROFILE_UPDATED" in actions


def test_breach_register_lifecycle(db_path):
    pm = PrivacyManager()
    ok, msg = pm.report_breach("2026-10-11T08:00:00", "SIM-swap attack on 3 accounts", "high", 3, ADMIN_PHONE)
    assert ok
    breach_id = int(msg.split("#")[1].split(" ")[0])

    breach = pm.get_breach(breach_id)
    assert breach["status"] == "open" and breach["severity"] == "high"
    assert len(pm.list_breaches()) == 1

    ok, _ = pm.update_breach(breach_id, status="investigating", actor=ADMIN_PHONE)
    assert ok
    ok, _ = pm.update_breach(breach_id, status="notified", reported_at="2026-10-12T09:00:00", actor=ADMIN_PHONE)
    assert ok
    ok, _ = pm.update_breach(breach_id, resolution="Tokens rotated; users notified", actor=ADMIN_PHONE)
    assert ok

    breach = pm.get_breach(breach_id)
    assert breach["status"] == "notified"
    assert breach["reported_at"] == "2026-10-12T09:00:00"
    assert breach["resolution"] == "Tokens rotated; users notified"
    assert len(pm.list_breaches(status="notified")) == 1
    assert len(pm.list_breaches(status="open")) == 0

    # Validation
    ok, _ = pm.report_breach("2026-10-11", "x", "catastrophic")
    assert not ok
    ok, _ = pm.report_breach("2026-10-11", "  ")
    assert not ok
    ok, _ = pm.update_breach(breach_id, status="bogus")
    assert not ok
    ok, _ = pm.update_breach(99999, status="open")
    assert not ok

    actions = [e.action for e in get_audit_logs(actor_phone=ADMIN_PHONE)]
    assert "BREACH_REPORTED" in actions and "BREACH_UPDATED" in actions


# --- REST API -------------------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient

    import mobile_money_system.api as api_module
    init_db()
    return TestClient(api_module.app), api_module


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_via_api(client, phone, name, accept=True):
    return client.post("/auth/register", json={
        "phone": phone, "name": name, "pin": "1234", "sec_q": "q", "sec_a": "a",
        "accept_terms": accept, "accept_privacy": accept})


def _login(client, phone, pin="1234") -> str:
    r = client.post("/auth/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_api_registration_requires_consent(db_path):
    client, _api = _client()

    # Missing flags -> validation error
    r = client.post("/auth/register", json={
        "phone": ALICE, "name": "Alice", "pin": "1234", "sec_q": "q", "sec_a": "a"})
    assert r.status_code == 422
    # Explicit refusal -> 400
    r = _register_via_api(client, ALICE, "Alice", accept=False)
    assert r.status_code == 400
    assert "must accept" in r.json()["detail"]
    # Acceptance -> registered + consent recorded in the ledger
    r = _register_via_api(client, ALICE, "Alice", accept=True)
    assert r.status_code == 200
    pm = PrivacyManager()
    assert pm.has_consent(ALICE, "terms")
    assert pm.has_consent(ALICE, "privacy")
    assert pm.active_consent(ALICE, "privacy")["policy_version"] == "1.0"


def test_api_legal_document_endpoint(db_path):
    client, _api = _client()
    r = client.get("/privacy/privacy_policy")
    assert r.status_code == 200
    assert r.json()["version"] == "1.0"
    assert "YOUR RIGHTS" in r.json()["content"]
    r = client.get("/privacy/terms_of_service")
    assert r.status_code == 200
    # Invalid document type -> validation error
    assert client.get("/privacy/cookie_banner").status_code == 422


def test_api_consent_ledger_endpoints(db_path):
    client, api_module = _client()
    _register_via_api(client, ALICE, "Alice")
    api_module.user_mgr.set_two_factor(ALICE, False)
    token = _login(client, ALICE)

    r = client.get("/me/consents", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["policy_update_required"] is False
    assert body["active_versions"]["privacy_policy"] == "1.0"
    purposes = {c["purpose"] for c in body["consents"]}
    assert {"terms", "privacy"} <= purposes

    # Marketing consent: accept then withdraw
    r = client.post("/me/consents", headers=_auth(token), json={"purpose": "marketing"})
    assert r.status_code == 200
    r = client.delete("/me/consents/marketing", headers=_auth(token))
    assert r.status_code == 200
    pm = PrivacyManager()
    assert not pm.has_consent(ALICE, "marketing")

    # Invalid purpose rejected
    r = client.post("/me/consents", headers=_auth(token), json={"purpose": "bogus"})
    assert r.status_code == 400

    # A new policy version flips the update-required flag
    pm.publish_document("privacy_policy", "2.0", "New policy...", ADMIN_PHONE)
    r = client.get("/me/consents", headers=_auth(token))
    assert r.json()["policy_update_required"] is True
    # Re-accept clears it
    r = client.post("/me/consents", headers=_auth(token), json={"purpose": "privacy"})
    assert r.status_code == 200
    r = client.get("/me/consents", headers=_auth(token))
    assert r.json()["policy_update_required"] is False


def test_api_profile_rectification(db_path):
    client, api_module = _client()
    _register_via_api(client, ALICE, "Alice")
    api_module.user_mgr.set_two_factor(ALICE, False)
    token = _login(client, ALICE)

    r = client.patch("/me/profile", headers=_auth(token), json={"name": "Alice Cooper"})
    assert r.status_code == 200
    r = client.get("/auth/me", headers=_auth(token))
    assert r.json()["name"] == "Alice Cooper"

    r = client.patch("/me/profile", headers=_auth(token), json={"name": "  "})
    assert r.status_code == 400


def test_api_admin_breach_register(db_path):
    client, _api = _client()
    r = client.post("/admin/breaches", json={
        "detected_at": "2026-10-11T08:00:00", "description": "Phishing page cloned the login",
        "severity": "medium", "affected_count": 12})
    assert r.status_code == 200
    breach_id = int(r.json()["message"].split("#")[1].split(" ")[0])

    r = client.get("/admin/breaches")
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.patch(f"/admin/breaches/{breach_id}",
                     json={"status": "notified", "reported_at": "2026-10-12T10:00:00"})
    assert r.status_code == 200
    r = client.get("/admin/breaches")
    assert r.json()[0]["status"] == "notified"

    r = client.post("/admin/breaches", json={"detected_at": "2026-10-11", "description": "x", "severity": "bogus"})
    assert r.status_code == 400


# --- Webapp UI (AppTest) ----------------------------------------------------------

def _patch_db(tmp_path, monkeypatch):
    """Point the TOP-LEVEL database module (the one app.py uses when run as a
    script) at a fresh tmp DB."""
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mobile_money_system")))
    import database as top_database
    monkeypatch.setattr(top_database, "DB_PATH", str(tmp_path / "apptest_privacy_laws.db"))


def _register_users():
    from database import get_db
    from users import UserManager
    um = UserManager()
    ok, msg = um.register(ALICE, "Alice", "1234", "q", "a")
    assert ok, msg
    ok, msg = um.register(ADMIN_PHONE, "Admin", "admin123", "q", "a")
    assert ok, msg
    with get_db() as conn:
        conn.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (ADMIN_PHONE,))
        conn.commit()


def test_settings_privacy_rights_section_renders(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    _patch_db(tmp_path, monkeypatch)
    _register_users()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = ALICE
    at.session_state["main_nav"] = "Settings"
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    headers = [m.value for m in at.markdown]
    assert any("Your Privacy Rights" in h for h in headers)
    assert any("Correct my data (rectification)" in h for h in headers)
    assert any("My consents" in h for h in headers)
    assert any("Legal documents" in h for h in headers)
    # Marketing consent toggle + the policy viewer expanders render
    assert any(t.label == "Marketing messages" for t in at.toggle)
    expander_labels = [e.label for e in at.expander]
    assert any("Privacy Policy v1.0" in label for label in expander_labels)


def test_admin_security_breach_register_renders(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    _patch_db(tmp_path, monkeypatch)
    _register_users()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.session_state["current_user_phone"] = ADMIN_PHONE
    at.session_state["admin_nav"] = "Security"
    at.run()
    assert not at.exception, [e.value for e in at.exception]

    headers = [m.value for m in at.markdown]
    assert any("Data Breach Register" in h for h in headers)
    assert any("Legal Documents" in h for h in headers)
    assert any(ta.label == "What happened?" for ta in at.text_area)
    assert any("No breaches recorded." in i.value for i in at.info)
