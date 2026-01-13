import json
import os
import time
import uuid
from datetime import datetime

class Transaction:
    def __init__(self, t_id, sender_phone, receiver_phone, amount, t_type, timestamp=None, description=""):
        self.id = t_id
        self.sender_phone = sender_phone
        self.receiver_phone = receiver_phone
        self.amount = amount
        self.type = t_type
        self.timestamp = timestamp or datetime.now().isoformat()
        self.description = description

    def to_dict(self):
        return {
            "id": self.id,
            "sender_phone": self.sender_phone,
            "receiver_phone": self.receiver_phone,
            "amount": self.amount,
            "type": self.type,
            "timestamp": self.timestamp,
            "description": self.description
        }
    
    @staticmethod
    def from_dict(data):
        return Transaction(
            data["id"], 
            data["sender_phone"], 
            data["receiver_phone"], 
            data["amount"], 
            data["type"], 
            data["timestamp"],
            description=data.get("description", "")
        )

class TransactionManager:
    def __init__(self, user_manager, db_file="transactions.json"):
        self.user_manager = user_manager
        self.db_file = db_file
        self.transactions = []
        self.load_transactions()
        
        # Configuration Limits (None currently active)
        pass 

    def load_transactions(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                data = json.load(f)
                self.transactions = [Transaction.from_dict(t) for t in data]

    def save_transactions(self):
        data = [t.to_dict() for t in self.transactions]
        with open(self.db_file, 'w') as f:
            json.dump(data, f, indent=4)

    def _check_limits(self, phone, amount):
        # No limits active
        return True, ""

    def _create_transaction_record(self, sender, receiver, amount, t_type, description=""):
        # Generate a standard reference number (e.g., TXN-12345678-ABCD)
        timestamp_part = int(time.time())
        random_part = str(uuid.uuid4())[:8].upper()
        t_id = f"TXN-{timestamp_part}-{random_part}"
        
        t = Transaction(t_id, sender, receiver, amount, t_type, description=description)
        self.transactions.append(t)
        self.save_transactions()
        return t

    def deposit(self, phone, amount, description="Deposit"):
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount <= 0:
            return False, "Invalid amount"
        
        # Standard users can only deposit max 5000 at once (e.g. from bank)
        if amount > 5000:
             return False, "Deposit limit exceeded (Max $5,000)"

        user.balance += amount
        self.user_manager.save_users()
        self._create_transaction_record("SYSTEM", phone, amount, "DEPOSIT", description)
        return True, f"Deposited {amount} successfully. New balance: {user.balance}"

    def withdraw(self, phone, amount, description="Withdrawal"):
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount <= 0:
            return False, "Invalid amount"
        
        # Check Limits
        allowed, msg = self._check_limits(phone, amount)
        if not allowed:
            return False, msg

        # 1% Withdrawal Fee
        fee = amount * 0.01
        total_deduction = amount + fee

        if user.balance < total_deduction:
            return False, f"Insufficient balance. Amount: ${amount} + Fee: ${fee:.2f}"
        
        user.balance -= total_deduction
        self.user_manager.save_users()
        
        # Main Withdrawal Record
        self._create_transaction_record(phone, "SYSTEM", amount, "WITHDRAWAL", description)
        # Fee Record
        self._create_transaction_record(phone, "SYSTEM_REVENUE", fee, "FEE", f"Fee for Withdrawal: {description}")
        
        return True, f"Withdrawn ${amount} + ${fee:.2f} fee. New balance: {user.balance:.2f}"

    def transfer(self, sender_phone, receiver_phone, amount, description="Transfer"):
        sender = self.user_manager.get_user(sender_phone)
        receiver = self.user_manager.get_user(receiver_phone)

        if not sender:
            return False, "Sender not found"
        if not receiver:
            return False, "Receiver not found"
        if sender_phone == receiver_phone:
            return False, "Cannot transfer to self"
        if amount <= 0:
            return False, "Invalid amount"
        
        # Check Limits
        allowed, msg = self._check_limits(sender_phone, amount)
        if not allowed:
            return False, msg

        # 1% Transfer Fee
        fee = amount * 0.01
        total_deduction = amount + fee

        if sender.balance < total_deduction:
            return False, f"Insufficient balance. Amount: ${amount} + Fee: ${fee:.2f}"

        sender.balance -= total_deduction
        receiver.balance += amount
        self.user_manager.save_users()
        
        # Transfer Record
        self._create_transaction_record(sender_phone, receiver_phone, amount, "TRANSFER", description)
        # Fee Record
        self._create_transaction_record(sender_phone, "SYSTEM_REVENUE", fee, "FEE", f"Fee for Transfer to {receiver.name}")
        
        return True, "Transfer successful"

    def pay_bill(self, phone, amount, biller_name, biller_id, description="Bill Payment"):
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount <= 0:
           return False, "Invalid amount"

        # Check Limits
        allowed, msg = self._check_limits(phone, amount)
        if not allowed:
            return False, msg

        # Fixed Bill Fee (e.g. $0.50)
        fee = 0.50
        total_deduction = amount + fee
        
        if user.balance < total_deduction:
             return False, f"Insufficient balance. Amount: ${amount} + Fee: ${fee:.2f}"
             
        user.balance -= total_deduction
        self.user_manager.save_users()
        
        # Bill Payment Record
        full_desc = f"{biller_name} ({biller_id}) - {description}"
        self._create_transaction_record(phone, "BILLER_SYSTEM", amount, "BILL_PAYMENT", full_desc)
        # Fee Record
        self._create_transaction_record(phone, "SYSTEM_REVENUE", fee, "FEE", f"Fee for Bill Pay: {biller_name}")
        
        return True, f"Paid {biller_name} successfully."

    def get_history(self, phone):
        history = [t for t in self.transactions if t.sender_phone == phone or t.receiver_phone == phone]
        return history
