"""Professionalism: API operational features — detailed health + idempotency keys."""

from mobile_money_system.database import init_db


def _client():
    from fastapi.testclient import TestClient

    import mobile_money_system.api as api_module
    init_db()  # ensure the patched tmp DB has tables
    return TestClient(api_module.app), api_module


def _register_funded_pair(api_module):
    ok, _ = api_module.user_mgr.register("+2348012345678", "Alice", "1234", "q", "a")
    assert ok
    api_module.user_mgr.submit_kyc("+2348012345678", "passport", "AB1234567")
    api_module.txn_mgr.admin_adjust_balance("+2348012345678", 1000.0, "seed")
    ok, _ = api_module.user_mgr.register("+2348087654321", "Bob", "1234", "q", "a")
    assert ok
    api_module.user_mgr.submit_kyc("+2348087654321", "passport", "CD7654321")


def test_health_reports_operational_detail(db_path):
    client, _api = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["journal_mode"] == "wal"
    assert isinstance(body["users"], int)
    assert isinstance(body["transactions"], int)
    assert body["uptime_seconds"] >= 0
    assert "version" in body


def test_idempotency_key_prevents_double_transfer(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    payload = {"sender_phone": "+2348012345678", "receiver_phone": "+2348087654321",
               "amount": 100, "description": "idem"}

    r1 = client.post("/transactions/transfer", json=payload, headers={"Idempotency-Key": "key-1"})
    assert r1.status_code == 200
    assert "reference" in r1.json()
    ref = r1.json()["reference"]
    assert r1.headers.get("X-Idempotent-Replay") is None

    # Same key -> replayed response, transfer NOT executed again
    r2 = client.post("/transactions/transfer", json=payload, headers={"Idempotency-Key": "key-1"})
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotent-Replay") == "true"
    assert r2.json()["reference"] == ref

    bob = api_module.user_mgr.get_user("+2348087654321")
    assert float(bob.balance) == 100.0


def test_different_idempotency_keys_execute_separately(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    payload = {"sender_phone": "+2348012345678", "receiver_phone": "+2348087654321",
               "amount": 100, "description": "idem"}
    r1 = client.post("/transactions/transfer", json=payload, headers={"Idempotency-Key": "key-1"})
    r2 = client.post("/transactions/transfer", json=payload, headers={"Idempotency-Key": "key-2"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.headers.get("X-Idempotent-Replay") is None
    assert r2.headers.get("X-Idempotent-Replay") is None
    bob = api_module.user_mgr.get_user("+2348087654321")
    assert float(bob.balance) == 200.0


def test_no_idempotency_key_executes_normally(db_path):
    client, api_module = _client()
    _register_funded_pair(api_module)
    payload = {"sender_phone": "+2348012345678", "receiver_phone": "+2348087654321",
               "amount": 100, "description": "no-key"}
    r1 = client.post("/transactions/transfer", json=payload)
    r2 = client.post("/transactions/transfer", json=payload)
    assert r1.status_code == 200 and r2.status_code == 200
    bob = api_module.user_mgr.get_user("+2348087654321")
    assert float(bob.balance) == 200.0
