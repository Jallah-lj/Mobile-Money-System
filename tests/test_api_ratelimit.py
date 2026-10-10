"""Tier 1 security pack: API rate limiting (unit + middleware via TestClient)."""

import pytest

from mobile_money_system.api import RateLimiter


def test_rate_limiter_allows_then_blocks():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    results = [rl.allow("client-a")[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_rate_limiter_retry_after_positive():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("client-b")[0] is True
    allowed, retry_after = rl.allow("client-b")
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_rate_limiter_window_slides():
    rl = RateLimiter(max_requests=2, window_seconds=0.2)
    assert rl.allow("client-c")[0] is True
    assert rl.allow("client-c")[0] is True
    assert rl.allow("client-c")[0] is False
    import time
    time.sleep(0.25)
    assert rl.allow("client-c")[0] is True


def test_rate_limiter_keys_are_independent():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("client-d")[0] is True
    assert rl.allow("client-e")[0] is True
    assert rl.allow("client-d")[0] is False


def _clear_limiter_state(api_module):
    for limiter in (api_module._general_limiter, api_module._login_limiter,
                    api_module._register_limiter):
        limiter._hits.clear()


def _ensure_schema():
    """api.py builds its manager singletons at import time (possibly before the
    db_path fixture patches DB_PATH) — make sure the patched tmp DB has tables."""
    from mobile_money_system.database import init_db
    init_db()


def test_login_endpoint_rate_limited(db_path):
    """The 11th login attempt within a minute from one IP gets HTTP 429."""
    from fastapi.testclient import TestClient
    import mobile_money_system.api as api_module
    _ensure_schema()
    _clear_limiter_state(api_module)

    client = TestClient(api_module.app)
    payload = {"phone": "+2348000000000", "pin": "0000"}
    statuses = [client.post("/users/login", json=payload).status_code for _ in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


def test_health_exempt_from_rate_limit(db_path):
    from fastapi.testclient import TestClient
    import mobile_money_system.api as api_module
    _ensure_schema()
    _clear_limiter_state(api_module)

    client = TestClient(api_module.app)
    # Hammer /health far beyond the general limit — it must stay exempt
    for _ in range(15):
        resp = client.get("/health")
        assert resp.status_code == 200


def test_general_rate_limit_applies(db_path):
    """Non-exempt endpoints get 429 after 120 requests/minute from one IP."""
    from fastapi.testclient import TestClient
    import mobile_money_system.api as api_module
    _ensure_schema()
    _clear_limiter_state(api_module)

    client = TestClient(api_module.app)
    # /users/{phone} hits the general limiter (no per-endpoint limit)
    last = None
    for i in range(121):
        last = client.get("/users/+2348000000000")
    assert last.status_code == 429
    assert "Retry-After" in last.headers
