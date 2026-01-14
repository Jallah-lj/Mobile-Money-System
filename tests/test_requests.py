import unittest
import sys
import os
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.users import UserManager, User

class MockUserManager:
    def __init__(self):
        self.users = {
            "requester": User("requester", "Alice", "1234", Decimal("100.0"), is_verified=True),
            "payer": User("payer", "Bob", "1234", Decimal("1000.0"), is_verified=True)
        }

    def get_user(self, phone):
        return self.users.get(phone)
    
    def save_users(self):
        pass

class TestRequests(unittest.TestCase):
    def setUp(self):
        self.user_manager = MockUserManager()
        self.tm = TransactionManager(self.user_manager)
        self.tm.transactions = []
        self.tm.save_transactions = lambda: None

    def test_request_cycle_pay(self):
        # Alice requests 50 from Bob
        success, msg = self.tm.request_money("requester", "payer", 50.0, "Lunch")
        self.assertTrue(success)
        
        # Verify Pending Transaction created
        pending = [t for t in self.tm.transactions if t.type == "REQUEST" and t.status == "PENDING"]
        self.assertEqual(len(pending), 1)
        req_id = pending[0].id
        
        # Bob pays
        success, msg = self.tm.process_request(req_id, "PAY")
        self.assertTrue(success)
        
        # Check balances
        # Payer (Bob) should lose 50 + 1% fee = 50.5
        self.assertEqual(self.user_manager.users["payer"].balance, Decimal("1000.0") - Decimal("50.5"))
        # Requester (Alice) should gain 50
        self.assertEqual(self.user_manager.users["requester"].balance, Decimal("100.0") + Decimal("50.0"))
        
        # Check original request status
        req_t = next(t for t in self.tm.transactions if t.id == req_id)
        self.assertEqual(req_t.status, "COMPLETED")

    def test_request_cycle_decline(self):
        # Alice requests 50 from Bob
        self.tm.request_money("requester", "payer", 50.0, "Lunch")
        req_id = self.tm.transactions[0].id
        
        # Bob declines
        success, msg = self.tm.process_request(req_id, "DECLINE")
        self.assertTrue(success)
        
        # Check balances unchanged
        self.assertEqual(self.user_manager.users["payer"].balance, 1000.0)
        
        # Check status
        req_t = next(t for t in self.tm.transactions if t.id == req_id)
        self.assertEqual(req_t.status, "DECLINED")

if __name__ == '__main__':
    unittest.main()
