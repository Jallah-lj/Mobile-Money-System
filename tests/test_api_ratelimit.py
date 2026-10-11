"""Tier 1 security pack: API rate limiting (unit + middleware via TestClient).

The limiter is DB-backed (rate_limit_hits table), so unit tests run against
the per-test tmp database and limits are shared across limiter instances —
which is exactly what makes them shared across server processes.
"""

from mobile_money_system.api import RateLimiter
from mobile_money_system.database import get_db, init_db


def test_rate_limiter_allows_then_blocks(db_path):
    init_db()
    rl = RateLimiter(max_requests=3, window_seconds=60)
    results = [rl.allow("client-a")[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_rate_limiter_retry_after_positive(db_path):
    init_db()
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("client-b")[0] is True
    allowed, retry_after = rl.allow("client-b")
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_rate_limiter_window_slides(db_path):
    init_db()
    rl = RateLimiter(max_requests=2, window_seconds=0.2)
    assert rl.allow("client-c")[0] is True
    assert rl.allow("client-c")[0] is True
    assert rl.allow("client-c")[0] is False
    import time
    time.sleep(0.25)
    assert rl.allow("client-c")[0] is True


def test_rate_limiter_keys_are_independent(db_path):
    init_db()
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("client-d")[0] is True
    assert rl.allow("client-e")[0] is True
    assert rl.allow("client-d")[0] is False


def test_rate_limiter_state_shared_across_instances(db_path):
    """Two limiter instances share the database — simulating two server workers."""
    init_db()
    rl1 = RateLimiter(max_requests=3, window_seconds=60)
    rl2 = RateLimiter(max_requests=3, window_seconds=60)
    assert [rl1.allow("shared-key")[0] for _ in range(3)] == [True] * 3
    # A second "worker" sees the same hits and is blocked
    assert rl2.allow("shared-key")[0] is False


def test_rate_limiter_survives_state_loss(db_path):
    """Hits persist in the DB: a fresh limiter instance enforces the same limit."""
    init_db()
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("persist-key")[0] is True
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM rate_limit_hits WHERE key = 'persist-key'").fetchone()[0]
    assert n == 1
    rl2 = RateLimiter(max_requests=1, window_seconds=60)
    assert rl2.allow("persist-key")[0] is False


def test_rate_limiter_reset(db_path):
    init_db()
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("reset-key")[0] is True
    assert rl.allow("reset-key")[0] is False
    rl.reset("reset-key")
    assert rl.allow("reset-key")[0] is True


def _clear_limiter_state(api_module):
    """The limiters hold no in-memory state anymore; clear the hits table."""
    with get_db() as conn:
        conn.execute("DELETE FROM rate_limit_hits")
        conn.commit()


def _ensure_schema():
    """api.py builds its manager singletons at import time (possibly before the
    db_path fixture patches DB_PATH) — make sure the patched tmp DB has tables."""
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
