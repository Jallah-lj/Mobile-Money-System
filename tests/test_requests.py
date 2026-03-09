import unittest
import sys
import os
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.models import User


class MockUserManager:
    def __init__(self):
        self._users = {
            "requester": User("requester", "Alice", "hashed", Decimal("100.0"),  is_verified=True),
            "payer":     User("payer",     "Bob",   "hashed", Decimal("1000.0"), is_verified=True),
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


class TestRequests(unittest.TestCase):
    def setUp(self):
        from tests.conftest import setup_test_db, insert_user
        self._db_path, self._db_teardown = setup_test_db()

        self.user_manager = MockUserManager()
        self.tm = TransactionManager(self.user_manager)

        insert_user("requester", "Alice", balance="100.0")
        insert_user("payer",     "Bob",   balance="1000.0")

    def tearDown(self):
        self._db_teardown()

    def test_request_cycle_pay(self):
        """Alice requests money from Bob; Bob pays — balances must update correctly."""
        success, msg = self.tm.request_money("requester", "payer", 50.0, "Lunch")
        self.assertTrue(success, msg)

        pending = [t for t in self.tm.transactions
                   if t.type == "REQUEST" and t.status == "PENDING"]
        self.assertEqual(len(pending), 1)
        req_id = pending[0].id

        success, msg = self.tm.process_request(req_id, "PAY")
        self.assertTrue(success, msg)

        from tests.conftest import get_balance
        self.assertEqual(get_balance("payer"),     Decimal("1000.0") - Decimal("50.5"))
        self.assertEqual(get_balance("requester"), Decimal("100.0")  + Decimal("50.0"))

        req_t = next(t for t in self.tm.transactions if t.id == req_id)
        self.assertEqual(req_t.status, "COMPLETED")

    def test_request_cycle_decline(self):
        """Bob declines Alice's request — no money should move."""
        self.tm.request_money("requester", "payer", 50.0, "Lunch")

        pending = [t for t in self.tm.transactions
                   if t.type == "REQUEST" and t.status == "PENDING"]
        self.assertEqual(len(pending), 1)
        req_id = pending[0].id

        success, msg = self.tm.process_request(req_id, "DECLINE")
        self.assertTrue(success, msg)

        from tests.conftest import get_balance
        self.assertEqual(get_balance("payer"), Decimal("1000.0"))

        req_t = next(t for t in self.tm.transactions if t.id == req_id)
        self.assertEqual(req_t.status, "DECLINED")


if __name__ == '__main__':
    unittest.main()

