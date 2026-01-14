import unittest
import sys
import os
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mobile_money_system.transactions import TransactionManager
from mobile_money_system.users import UserManager, User

class MockUserManagerCompliance:
    def __init__(self):
        self.users = {
            "verified_sender": User("verified_sender", "Ver Sender", "1234", Decimal("50000.0"), is_verified=True),
            "unverified_sender": User("unverified_sender", "Unver Sender", "1234", Decimal("50000.0"), is_verified=False),
            "receiver": User("receiver", "Receiver", "1234", Decimal("100.0"), is_verified=True),
        }
    
    def get_user(self, phone):
        return self.users.get(phone)
    
    def save_users(self):
        pass

class TestCompliance(unittest.TestCase):
    def setUp(self):
        self.user_manager = MockUserManagerCompliance()
        self.tm = TransactionManager(self.user_manager)
        self.tm.transactions = []
        self.tm.save_transactions = lambda: None
        # Mock ledger to avoid file IO issues with LedgerManager inside TransactionManager
        self.tm.ledger.create_entry = lambda *args: None
        self.tm.ledger.post_entries = lambda *args: True 

    def test_kyc_block(self):
        # Unverified user tries to transfer
        success, msg = self.tm.transfer("unverified_sender", "receiver", 100.0)
        self.assertFalse(success)
        self.assertIn("KYC Not Verified", msg)

    def test_aml_flagging_large_amount(self):
        # Verified user sends > 10,000
        success, msg = self.tm.transfer("verified_sender", "receiver", 15000.0)
        self.assertTrue(success) 
        # Transaction should succeed but be flagged
        
        # Check the transactions. There should be Transfer and Fee.
        # The Transfer is likely -2, Fee is -1.
        txn = self.tm.transactions[-2]
        self.assertEqual(txn.type, "TRANSFER")
        self.assertTrue(txn.flagged)
        self.assertIn("Large amount", txn.flag_reason)

    def test_aml_flagging_velocity(self):
        # Verified user sends rapid small amounts
        # We need to manually inject transactions into history to simulate past volume
        import datetime
        from mobile_money_system.models import Transaction
        
        now = datetime.datetime.now()
        
        # Inject 5 recent transactions
        for i in range(5):
             t = Transaction(
                 id=f"hist_{i}",
                 sender_phone="verified_sender",
                 receiver_phone="receiver",
                 amount=Decimal("100.0"),
                 type="TRANSFER",
                 currency="USD",
                 timestamp=now.isoformat()
             )
             self.tm.transactions.append(t)
             
        # Now try one more
        success, msg = self.tm.transfer("verified_sender", "receiver", 100.0)
        self.assertTrue(success)
        
        txn = self.tm.transactions[-2]
        self.assertEqual(txn.type, "TRANSFER")
        self.assertTrue(txn.flagged)
        self.assertIn("Velocity", txn.flag_reason)

if __name__ == '__main__':
    unittest.main()
