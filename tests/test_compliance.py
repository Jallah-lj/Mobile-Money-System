import unittest
import sys
import os
from decimal import Decimal
from datetime import datetime, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.models import User


class MockUserManagerCompliance:
    def __init__(self):
        self._users = {
            "verified_sender": User("verified_sender", "Ver Sender", "hashed",
                                    Decimal("50000.0"), is_verified=True, risk_tier="high"),
            "unverified_sender": User("unverified_sender", "Unver Sender", "hashed",
                                      Decimal("50000.0"), is_verified=False),
            "receiver": User("receiver", "Receiver", "hashed",
                             Decimal("100.0"), is_verified=True),
        }

    def get_user(self, phone):
        user = self._users.get(phone)
        if user is None:
            return None
        from tests.conftest import get_balance
        user.balance = get_balance(phone)
        return user

    def update_user(self, phone, **kwargs):
        user = self._users.get(phone)
        if user and "balance" in kwargs:
            user.balance = Decimal(str(kwargs["balance"]))
        return True, "Updated"

    def save_users(self):
        pass


class TestCompliance(unittest.TestCase):
    def setUp(self):
        from tests.conftest import setup_test_db, insert_user
        self._db_path, self._db_teardown = setup_test_db()

        self.user_manager = MockUserManagerCompliance()
        self.tm = TransactionManager(self.user_manager)

        insert_user("verified_sender",   "Ver Sender",   balance="50000.0", risk_tier="high")
        insert_user("unverified_sender", "Unver Sender", balance="50000.0", is_verified=False)
        insert_user("receiver",          "Receiver",     balance="100.0")

    def tearDown(self):
        self._db_teardown()

    def test_kyc_block(self):
        """Unverified users must be blocked from transferring."""
        success, msg = self.tm.transfer("unverified_sender", "receiver", 100.0)
        self.assertFalse(success)
        self.assertIn("KYC Not Verified", msg)

    def test_aml_flagging_large_amount(self):
        """Transfers > $10,000 must be flagged for AML review."""
        success, msg = self.tm.transfer("verified_sender", "receiver", 15000.0)
        self.assertTrue(success, msg)

        all_txns = self.tm.transactions
        transfer_txns = [t for t in all_txns if t.type == "TRANSFER"]
        self.assertTrue(len(transfer_txns) >= 1)
        txn = transfer_txns[-1]
        self.assertEqual(txn.type, "TRANSFER")
        self.assertTrue(txn.flagged)
        self.assertIn("Large amount", txn.flag_reason)

    def test_aml_flagging_velocity(self):
        """A burst of rapid transactions must trigger the velocity flag."""
        from tests.conftest import get_test_conn
        conn = get_test_conn()
        now = datetime.now(timezone.utc).isoformat()
        for i in range(5):
            conn.execute(
                """INSERT INTO transactions
                   (id, sender_phone, receiver_phone, amount, currency, type, timestamp, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"hist_{i}", "verified_sender", "receiver",
                 "100.0", "USD", "TRANSFER", now, "COMPLETED")
            )
        conn.commit()
        conn.close()

        success, msg = self.tm.transfer("verified_sender", "receiver", 100.0)
        self.assertTrue(success, msg)

        all_txns = self.tm.transactions
        transfer_txns = [t for t in all_txns
                         if t.type == "TRANSFER" and not t.id.startswith("hist_")]
        self.assertTrue(len(transfer_txns) >= 1)
        txn = transfer_txns[-1]
        self.assertTrue(txn.flagged)
        self.assertIn("Velocity", txn.flag_reason)


if __name__ == '__main__':
    unittest.main()

