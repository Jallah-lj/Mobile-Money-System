"""Mobile app API: Bearer-token auth (/auth/*) + token-scoped /me/* endpoints.

The app-facing API identifies the user from the session token, never from the
request body. Tokens are rows in the existing `sessions` table
(provider="mobile"), so revocation and "log out everywhere" work for app
sessions too.
"""

from mobile_money_system.database import init_db

ALICE = "+2348012345678"
BOB = "+2348087654321"
CAROL = "+2348011112222"


def _client():
    from fastapi.testclient import TestClient

    import mobile_money_system.api as api_module
    init_db()  # ensure the patched tmp DB has tables
    return TestClient(api_module.app), api_module


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_funded_pair(api_module):
    ok, _ = api_module.user_mgr.register(ALICE, "Alice", "1234", "q", "a")
    assert ok
    api_module.user_mgr.set_two_factor(ALICE, False)  # 2FA is default-ON; tests log in with PIN only
    api_module.user_mgr.submit_kyc(ALICE, "passport", "AB1234567")
    api_module.txn_mgr.admin_adjust_balance(ALICE, 1000.0, "seed")
    ok, _ = api_module.user_mgr.register(BOB, "Bob", "1234", "q", "a")
    assert ok
    api_module.user_mgr.set_two_factor(BOB, False)
    api_module.user_mgr.submit_kyc(BOB, "passport", "CD7654321")


def _login(client, phone, pin="1234") -> str:
    r = client.post("/auth/login", json={"phone": phone, "pin": pin})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "requires_otp" not in body
    return body["access_token"]


# --- Auth ---------------------------------------------------------------------

def test_register_login_me_flow(db_path):
    client, api_module = _client()
    r = client.post("/auth/register", json={
        "phone": ALICE, "name": "Alice", "pin": "1234", "sec_q": "q", "sec_a": "a"})
    assert r.status_code == 200
    api_module.user_mgr.set_two_factor(ALICE, False)  # PIN-only login for this test

    r = client.post("/auth/login", json={"phone": ALICE, "pin": "1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["phone"] == ALICE
    assert "pin" not in body["user"]

    r = client.get("/auth/me", headers=_auth(body["access_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "Alice"


def test_login_wrong_pin_rejected(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    r = client.post("/auth/login", json={"phone": ALICE, "pin": "9999"})
    assert r.status_code == 401


def test_app_endpoints_require_valid_token(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=_auth("garbage-token")).status_code == 401
    assert client.get("/me/history", headers=_auth("garbage-token")).status_code == 401


def test_logout_revokes_token(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    token = _login(client, ALICE)
    assert client.get("/auth/me", headers=_auth(token)).status_code == 200
    r = client.post("/auth/logout", headers=_auth(token))
    assert r.status_code == 200
    assert client.get("/auth/me", headers=_auth(token)).status_code == 401


def test_login_with_2fa_requires_otp(db_path, monkeypatch):
    client, api_module = _client()
    _register_funded_pair(api_module)
    ok, _ = api_module.user_mgr.set_two_factor(ALICE, True)
    assert ok
    issued_codes = {}
    real_generate_otp = api_module.user_mgr.generate_otp

    def spy_generate_otp(phone):
        code = real_generate_otp(phone)  # stores the hash, like production
        issued_codes[phone] = code
        return code

    monkeypatch.setattr(api_module.user_mgr, "generate_otp", spy_generate_otp)

    r = client.post("/auth/login", json={"phone": ALICE, "pin": "1234"})
    assert r.status_code == 200
    assert r.json()["requires_otp"] is True
    assert "access_token" not in r.json()
    code = issued_codes[ALICE]

    # Wrong code -> 401 (and does not consume the code); right code -> token
    r = client.post("/auth/verify-otp", json={"phone": ALICE, "code": "000000"})
    assert r.status_code == 401
    r = client.post("/auth/verify-otp", json={"phone": ALICE, "code": code})
    assert r.status_code == 200
    token = r.json()["access_token"]
    r = client.get("/auth/me", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["phone"] == ALICE


# --- Wallet -------------------------------------------------------------------

def test_transfer_between_users(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    _login(client, BOB)

    r = client.post("/me/transfer", headers=_auth(alice),
                    json={"receiver_phone": BOB, "amount": 100, "description": "gift"})
    assert r.status_code == 200
    assert r.json()["reference"]
    assert float(api_module.user_mgr.get_user(ALICE).balance) == 900.0
    assert float(api_module.user_mgr.get_user(BOB).balance) == 100.0

    # History shows the transfer; recent recipients track Bob for Alice
    r = client.get("/me/history", headers=_auth(alice))
    assert r.status_code == 200
    assert r.json()["transactions"][0]["type"] == "TRANSFER"
    r = client.get("/me/recent-recipients", headers=_auth(alice))
    assert BOB in r.json()["recipients"]


def test_transfer_idempotency_replay(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    headers = {**_auth(alice), "Idempotency-Key": "app-key-1"}
    payload = {"receiver_phone": BOB, "amount": 100}

    r1 = client.post("/me/transfer", headers=headers, json=payload)
    assert r1.status_code == 200
    ref = r1.json()["reference"]

    r2 = client.post("/me/transfer", headers=headers, json=payload)
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotent-Replay") == "true"
    assert r2.json()["reference"] == ref
    assert float(api_module.user_mgr.get_user(BOB).balance) == 100.0


def test_transfer_validation_errors(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)

    r = client.post("/me/transfer", headers=_auth(alice),
                    json={"receiver_phone": ALICE, "amount": 10})
    assert r.status_code == 400
    r = client.post("/me/transfer", headers=_auth(alice),
                    json={"receiver_phone": "+2349999999999", "amount": 10})
    assert r.status_code == 400
    r = client.post("/me/transfer", headers=_auth(alice),
                    json={"receiver_phone": BOB, "amount": 999999})
    assert r.status_code == 400


def test_money_request_pay_and_decline(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    api_module.txn_mgr.admin_adjust_balance(BOB, 200.0, "seed")
    alice = _login(client, ALICE)
    bob = _login(client, BOB)

    r = client.post("/me/request", headers=_auth(alice),
                    json={"payer_phone": BOB, "amount": 50, "description": "dinner"})
    assert r.status_code == 200

    # Bob sees it as incoming; Alice as outgoing
    r = client.get("/me/requests", headers=_auth(bob))
    requests = r.json()["requests"]
    assert len(requests) == 1
    assert requests[0]["direction"] == "incoming"
    assert requests[0]["status"] == "PENDING"
    t_id = requests[0]["id"]
    r = client.get("/me/requests", headers=_auth(alice))
    assert r.json()["requests"][0]["direction"] == "outgoing"

    # Only the payer can act on it
    r = client.post(f"/me/requests/{t_id}/pay", headers=_auth(alice))
    assert r.status_code == 404

    r = client.post(f"/me/requests/{t_id}/pay", headers=_auth(bob))
    assert r.status_code == 200
    assert float(api_module.user_mgr.get_user(BOB).balance) == 150.0
    assert float(api_module.user_mgr.get_user(ALICE).balance) == 1050.0

    # A second request, declined
    client.post("/me/request", headers=_auth(alice), json={"payer_phone": BOB, "amount": 30})
    r = client.get("/me/requests", headers=_auth(bob))
    pending = [q for q in r.json()["requests"] if q["status"] == "PENDING"]
    assert len(pending) == 1
    r = client.post(f"/me/requests/{pending[0]['id']}/decline", headers=_auth(bob))
    assert r.status_code == 200
    assert float(api_module.user_mgr.get_user(BOB).balance) == 150.0


# --- Bills --------------------------------------------------------------------

def test_billers_catalog_and_pay_bill(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    ok, _ = api_module.biller_mgr.add("Test Electric", "Electricity (Prepaid)", "ELEC-01")
    assert ok
    billers = api_module.biller_mgr.list(active_only=True)
    biller_id = billers[0]["id"]

    r = client.get("/billers", headers=_auth(alice))
    assert r.status_code == 200
    body = r.json()
    assert "Electricity (Prepaid)" in body["categories"]
    assert body["billers"][0]["biller_id"] == "ELEC-01"

    # Bill payment deducts amount + flat fee (default $0.25)
    r = client.post("/me/pay-bill", headers=_auth(alice),
                    json={"biller_id": biller_id, "amount": 100})
    assert r.status_code == 200
    assert float(api_module.user_mgr.get_user(ALICE).balance) == 899.75

    r = client.post("/me/pay-bill", headers=_auth(alice),
                    json={"biller_id": 99999, "amount": 100})
    assert r.status_code == 404


# --- Beneficiaries --------------------------------------------------------------

def test_beneficiaries_crud(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)

    r = client.post("/me/beneficiaries", headers=_auth(alice),
                    json={"phone": BOB, "nickname": "Bobby"})
    assert r.status_code == 200

    r = client.get("/me/beneficiaries", headers=_auth(alice))
    bens = r.json()["beneficiaries"]
    assert len(bens) == 1
    assert bens[0]["phone"] == BOB
    assert bens[0]["nickname"] == "Bobby"
    assert bens[0]["is_registered"] is True

    # Other users cannot see or remove Alice's beneficiaries
    bob = _login(client, BOB)
    r = client.get("/me/beneficiaries", headers=_auth(bob))
    assert r.json()["beneficiaries"] == []
    r = client.delete(f"/me/beneficiaries/{BOB}", headers=_auth(bob))
    assert r.status_code == 404

    r = client.delete(f"/me/beneficiaries/{BOB}", headers=_auth(alice))
    assert r.status_code == 200
    r = client.get("/me/beneficiaries", headers=_auth(alice))
    assert r.json()["beneficiaries"] == []


# --- Scheduled payments -----------------------------------------------------------

def test_scheduled_create_pause_cancel(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    bob = _login(client, BOB)

    r = client.post("/me/scheduled", headers=_auth(alice), json={
        "type": "TRANSFER", "amount": 25, "receiver_phone": BOB, "frequency": "weekly"})
    assert r.status_code == 200

    r = client.get("/me/scheduled", headers=_auth(alice))
    scheduled = r.json()["scheduled"]
    assert len(scheduled) == 1
    sp_id = scheduled[0]["id"]
    assert scheduled[0]["active"] == 1

    # Pause + resume
    r = client.patch(f"/me/scheduled/{sp_id}", headers=_auth(alice), json={"active": False})
    assert r.status_code == 200
    r = client.patch(f"/me/scheduled/{sp_id}", headers=_auth(alice), json={"active": True})
    assert r.status_code == 200

    # Only the owner can cancel
    r = client.post(f"/me/scheduled/{sp_id}/cancel", headers=_auth(bob))
    assert r.status_code == 404
    r = client.post(f"/me/scheduled/{sp_id}/cancel", headers=_auth(alice))
    assert r.status_code == 200
    r = client.get("/me/scheduled", headers=_auth(alice))
    assert r.json()["scheduled"][0]["active"] == 0


def test_scheduled_invalid_type_rejected(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    r = client.post("/me/scheduled", headers=_auth(alice),
                    json={"type": "ROCKET", "amount": 25, "receiver_phone": BOB})
    assert r.status_code == 400


# --- Support tickets ---------------------------------------------------------------

def test_tickets_create_list_get(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    alice = _login(client, ALICE)
    bob = _login(client, BOB)

    r = client.post("/me/tickets", headers=_auth(alice), json={
        "subject": "Card issue", "category": "payment", "message": "My card was declined."})
    assert r.status_code == 200

    r = client.get("/me/tickets", headers=_auth(alice))
    tickets = r.json()["tickets"]
    assert len(tickets) == 1
    ticket_id = tickets[0]["id"]

    r = client.get(f"/me/tickets/{ticket_id}", headers=_auth(alice))
    assert r.status_code == 200
    assert r.json()["subject"] == "Card issue"

    # Tickets are private to their owner
    r = client.get(f"/me/tickets/{ticket_id}", headers=_auth(bob))
    assert r.status_code == 404

    r = client.post("/me/tickets", headers=_auth(alice),
                    json={"subject": "x", "category": "bogus", "message": "y"})
    assert r.status_code == 400


# --- KYC + privacy ------------------------------------------------------------------

def test_kyc_and_data_export(db_path):
    client, api_module = _client()
    ok, _ = api_module.user_mgr.register(CAROL, "Carol", "1234", "q", "a")
    assert ok
    api_module.user_mgr.set_two_factor(CAROL, False)
    carol = _login(client, CAROL)

    r = client.post("/me/kyc", headers=_auth(carol),
                    json={"id_type": "passport", "id_number": "XY9876543"})
    assert r.status_code == 200
    r = client.get("/auth/me", headers=_auth(carol))
    assert r.json()["is_verified"] == 1

    r = client.get("/me/data-export", headers=_auth(carol))
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["phone"] == CAROL
    assert "pin" not in body["profile"]
    assert isinstance(body["transactions"], list)
