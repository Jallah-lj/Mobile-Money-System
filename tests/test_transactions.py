import unittest
import sys
import os
from decimal import Decimal

# Add parent directory to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.models import User


class MockUserManager:
    """Lightweight stand-in; get_user reads balance from the test DB."""

    def __init__(self):
        self._users = {
            "sender":   User("sender",   "Sender",   "hashed", Decimal("10000.0"), is_verified=True),
            "receiver": User("receiver", "Receiver", "hashed", Decimal("100.0"),   is_verified=True),
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


class TestTransactionLimits(unittest.TestCase):
    def setUp(self):
        from tests.conftest import setup_test_db, insert_user
        self._db_path, self._db_teardown = setup_test_db()

        self.user_manager = MockUserManager()
        self.tm = TransactionManager(self.user_manager)

        insert_user("sender",   "Sender",   balance="10000.0")
        insert_user("receiver", "Receiver", balance="100.0")

    def tearDown(self):
        self._db_teardown()

    def test_fees(self):
        """Transfer fee must be exactly 1% and receiver must get the full amount."""
        amount = Decimal("100")

        success, msg = self.tm.transfer("sender", "receiver", float(amount), "Fee Test")
        self.assertTrue(success, msg)

        fee = amount * Decimal("0.01")

        from tests.conftest import get_balance
        self.assertEqual(get_balance("sender"),   Decimal("10000.0") - amount - fee)
        self.assertEqual(get_balance("receiver"), Decimal("100.0")   + amount)


if __name__ == '__main__':
    unittest.main()

