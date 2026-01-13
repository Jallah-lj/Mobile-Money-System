import unittest
import sys
import os

# Add parent directory to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.users import UserManager, User

class MockUserManager:
    def __init__(self):
        self.users = {
            "sender": User("sender", "Sender", "1234", 10000.0),
            "receiver": User("receiver", "Receiver", "1234", 100.0),
            "rich_guy": User("rich_guy", "Rich", "1234", 100000.0)
        }
    
    def get_user(self, phone):
        return self.users.get(phone)
    
    def save_users(self):
        pass # Mock save

class TestTransactionLimits(unittest.TestCase):
    def setUp(self):
        self.user_manager = MockUserManager()
        # Point to a temporary file or mock storage logic if needed
        self.tm = TransactionManager(self.user_manager)
        self.tm.transactions = [] # Clear history
        self.tm.save_transactions = lambda: None # Mock save

    def test_fees(self):
        # Transfer fee is 1%
        sender_start = self.user_manager.users["sender"].balance
        receiver_start = self.user_manager.users["receiver"].balance
        amount = 100
        
        success, msg = self.tm.transfer("sender", "receiver", amount, "Fee Test")
        self.assertTrue(success)
        
        fee = amount * 0.01
        
        # Check Sender deducted amount + fee
        self.assertEqual(self.user_manager.users["sender"].balance, sender_start - amount - fee)
        # Check Receiver got amount
        self.assertEqual(self.user_manager.users["receiver"].balance, receiver_start + amount)

if __name__ == '__main__':
    unittest.main()
