"""
Tests for security fixes:
  - Plain-text PIN fallback removed from login
  - OTP master bypass code removed
  - Sensitive fields stripped from API GET /users/{phone}
  - API key required on all endpoints
  - Input validation (phone format, amount > 0)
  - request_money validates KYC/status for both parties
  - reverse_transaction blocks negative receiver balance
"""
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.users import UserManager
from mobile_money_system.models import User
from mobile_money_system.transactions import TransactionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockStorage:
    """In-memory storage mock – no file I/O."""
    def load(self, default=None):
        return default if default is not None else {}

    def save(self, data):
        pass


class _BaseUserManager(UserManager):
    """UserManager that uses in-memory storage and skips default admin creation."""
    def __init__(self):
        from mobile_money_system.storage import JsonStorage
        self.storage = MockStorage()
        self.users = {}
        self.otp_storage = {}


class MockUserManagerForTxn:
    """Minimal mock used by TransactionManager tests."""
    def __init__(self, users):
        self.users = users

    def get_user(self, phone):
        return self.users.get(phone)

    def save_users(self):
        pass


# ---------------------------------------------------------------------------
# Login security
# ---------------------------------------------------------------------------

class TestLoginSecurity(unittest.TestCase):
    def setUp(self):
        self.um = _BaseUserManager()
        # Register a user with a hashed PIN
        import hashlib
        hashed = hashlib.sha256("secret".encode()).hexdigest()
        self.um.users["1234567890"] = User(
            phone="1234567890", name="Alice", pin=hashed, is_verified=True
        )

    def test_correct_hash_login_succeeds(self):
        user = self.um.login("1234567890", "secret")
        self.assertIsNotNone(user)

    def test_wrong_pin_rejected(self):
        user = self.um.login("1234567890", "wrong")
        self.assertIsNone(user)

    def test_plaintext_pin_is_rejected(self):
        """The plain-text fallback must no longer be accepted."""
        import hashlib
        plain_pin = "secret"
        # Manually store the plain-text PIN (simulating a legacy record)
        self.um.users["1234567890"].pin = plain_pin
        user = self.um.login("1234567890", plain_pin)
        self.assertIsNone(user, "Plain-text PIN must not authenticate after security fix")


# ---------------------------------------------------------------------------
# OTP – no master bypass
# ---------------------------------------------------------------------------

class TestOTPSecurity(unittest.TestCase):
    def setUp(self):
        self.um = _BaseUserManager()
        self.um.users["1234567890"] = User(phone="1234567890", name="Bob", pin="x")

    def test_real_otp_works(self):
        code = self.um.generate_otp("1234567890")
        self.assertTrue(self.um.verify_otp("1234567890", code))

    def test_hardcoded_master_code_rejected(self):
        """The backdoor '123456' must no longer bypass OTP verification."""
        # Ensure 123456 is NOT the generated code by generating a fresh OTP
        import random
        with patch.object(random, 'randint', return_value=999999):
            self.um.generate_otp("1234567890")
        # Now try the old master code
        result = self.um.verify_otp("1234567890", "123456")
        self.assertFalse(result, "Hardcoded master OTP bypass must be removed")

    def test_expired_otp_rejected(self):
        import time
        code = self.um.generate_otp("1234567890")
        # Manually expire the OTP
        self.um.otp_storage["1234567890"]["expiry"] = time.time() - 1
        self.assertFalse(self.um.verify_otp("1234567890", code))


# ---------------------------------------------------------------------------
# API – key authentication and input validation
# ---------------------------------------------------------------------------

class TestAPIKeyAuth(unittest.TestCase):
    """FastAPI endpoint tests using TestClient."""

    def setUp(self):
        os.environ["API_KEY"] = "test-secret-key"
        # Import after setting env var so the app picks it up
        from fastapi.testclient import TestClient
        from mobile_money_system.api import app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.valid_headers = {"X-API-Key": "test-secret-key"}

    def test_missing_api_key_returns_401(self):
        resp = self.client.get("/users/1234567890")
        self.assertEqual(resp.status_code, 401)

    def test_wrong_api_key_returns_403(self):
        resp = self.client.get("/users/1234567890", headers={"X-API-Key": "wrong"})
        self.assertEqual(resp.status_code, 403)

    def test_valid_api_key_accepted(self):
        resp = self.client.get("/users/9999999999", headers=self.valid_headers)
        # 404 is fine – means auth passed, user not found
        self.assertIn(resp.status_code, [200, 404])

    def test_get_user_does_not_expose_pin(self):
        """The API must never return pin or sec_a fields."""
        from mobile_money_system.api import user_mgr
        import hashlib
        user_mgr.users["9990000001"] = User(
            phone="9990000001",
            name="Test",
            pin=hashlib.sha256("1234".encode()).hexdigest(),
            sec_a=hashlib.sha256("ans".encode()).hexdigest(),
            is_verified=True,
        )
        resp = self.client.get("/users/9990000001", headers=self.valid_headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn("pin", body, "pin hash must not appear in response")
        self.assertNotIn("sec_a", body, "sec_a hash must not appear in response")


class TestAPIInputValidation(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEY"] = "test-secret-key"
        from fastapi.testclient import TestClient
        from mobile_money_system.api import app
        self.client = TestClient(app, raise_server_exceptions=False)
        self.h = {"X-API-Key": "test-secret-key"}

    def test_register_invalid_phone_rejected(self):
        resp = self.client.post("/users/register", json={
            "phone": "abc",
            "name": "X", "pin": "1234", "sec_q": "q", "sec_a": "a"
        }, headers=self.h)
        self.assertEqual(resp.status_code, 422)

    def test_register_short_pin_rejected(self):
        resp = self.client.post("/users/register", json={
            "phone": "1234567890",
            "name": "X", "pin": "123", "sec_q": "q", "sec_a": "a"
        }, headers=self.h)
        self.assertEqual(resp.status_code, 422)

    def test_deposit_negative_amount_rejected(self):
        resp = self.client.post("/transactions/deposit", json={
            "phone": "1234567890", "amount": -50.0
        }, headers=self.h)
        self.assertEqual(resp.status_code, 422)

    def test_deposit_zero_amount_rejected(self):
        resp = self.client.post("/transactions/deposit", json={
            "phone": "1234567890", "amount": 0
        }, headers=self.h)
        self.assertEqual(resp.status_code, 422)

    def test_transfer_invalid_sender_phone_rejected(self):
        resp = self.client.post("/transactions/transfer", json={
            "sender_phone": "short", "receiver_phone": "1234567890",
            "amount": 100.0
        }, headers=self.h)
        self.assertEqual(resp.status_code, 422)


# ---------------------------------------------------------------------------
# Transaction flow – request_money KYC validation
# ---------------------------------------------------------------------------

class TestRequestMoneyValidation(unittest.TestCase):
    def _make_tm(self, users):
        um = MockUserManagerForTxn(users)
        tm = TransactionManager(um)
        tm.transactions = []
        tm.save_transactions = lambda: None
        return tm

    def test_unverified_requester_blocked(self):
        users = {
            "req": User("req", "Alice", "x", Decimal("100"), is_verified=False, status="active"),
            "pay": User("pay", "Bob", "x", Decimal("500"), is_verified=True, status="active"),
        }
        tm = self._make_tm(users)
        ok, msg = tm.request_money("req", "pay", 50.0)
        self.assertFalse(ok)
        self.assertIn("KYC", msg)

    def test_unverified_payer_blocked(self):
        users = {
            "req": User("req", "Alice", "x", Decimal("100"), is_verified=True, status="active"),
            "pay": User("pay", "Bob", "x", Decimal("500"), is_verified=False, status="active"),
        }
        tm = self._make_tm(users)
        ok, msg = tm.request_money("req", "pay", 50.0)
        self.assertFalse(ok)
        self.assertIn("KYC", msg)

    def test_suspended_requester_blocked(self):
        users = {
            "req": User("req", "Alice", "x", Decimal("100"), is_verified=True, status="suspended"),
            "pay": User("pay", "Bob", "x", Decimal("500"), is_verified=True, status="active"),
        }
        tm = self._make_tm(users)
        ok, msg = tm.request_money("req", "pay", 50.0)
        self.assertFalse(ok)
        self.assertIn("suspended", msg)

    def test_verified_active_users_can_request(self):
        users = {
            "req": User("req", "Alice", "x", Decimal("100"), is_verified=True, status="active"),
            "pay": User("pay", "Bob", "x", Decimal("500"), is_verified=True, status="active"),
        }
        tm = self._make_tm(users)
        tm.ledger.create_entry = lambda *a, **kw: None
        tm.ledger.post_entries = lambda *a, **kw: True
        ok, _ = tm.request_money("req", "pay", 50.0)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# Transaction flow – reverse_transaction blocks negative receiver balance
# ---------------------------------------------------------------------------

class TestReverseTransactionSafety(unittest.TestCase):
    def _make_tm(self, users):
        um = MockUserManagerForTxn(users)
        tm = TransactionManager(um)
        tm.transactions = []
        tm.save_transactions = lambda: None
        return tm

    def test_reversal_blocked_when_receiver_balance_insufficient(self):
        from mobile_money_system.models import Transaction
        users = {
            "alice": User("alice", "Alice", "x", Decimal("0"), is_verified=True, status="active"),
            "bob":   User("bob",   "Bob",   "x", Decimal("10"), is_verified=True, status="active"),
        }
        tm = self._make_tm(users)
        # Inject a completed TRANSFER transaction
        txn = Transaction(
            id="TXN-TEST-1234",
            sender_phone="alice",
            receiver_phone="bob",
            amount=Decimal("50"),
            currency="USD",
            type="TRANSFER",
        )
        tm.transactions.append(txn)
        # Bob only has $10, but the original transfer was $50 → reversal should be blocked
        ok, msg = tm.reverse_transaction("TXN-TEST-1234")
        self.assertFalse(ok)
        self.assertIn("insufficient", msg.lower())

    def test_reversal_succeeds_when_receiver_has_funds(self):
        from mobile_money_system.models import Transaction
        users = {
            "alice": User("alice", "Alice", "x", Decimal("0"),   is_verified=True, status="active"),
            "bob":   User("bob",   "Bob",   "x", Decimal("200"), is_verified=True, status="active"),
        }
        tm = self._make_tm(users)
        txn = Transaction(
            id="TXN-TEST-5678",
            sender_phone="alice",
            receiver_phone="bob",
            amount=Decimal("50"),
            currency="USD",
            type="TRANSFER",
        )
        tm.transactions.append(txn)
        ok, _ = tm.reverse_transaction("TXN-TEST-5678")
        self.assertTrue(ok)
        self.assertEqual(users["alice"].balance, Decimal("50"))
        self.assertEqual(users["bob"].balance, Decimal("150"))


if __name__ == "__main__":
    unittest.main()
