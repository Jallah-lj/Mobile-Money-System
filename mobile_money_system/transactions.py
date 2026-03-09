import time
import uuid
import sqlite3
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from decimal import Decimal

try:
    from models import Transaction
    from database import get_db
    from users import UserManager
    from ledger import LedgerManager
except ImportError:
    from mobile_money_system.models import Transaction
    from mobile_money_system.database import get_db
    from mobile_money_system.users import UserManager
    from mobile_money_system.ledger import LedgerManager

class TransactionManager:
    def __init__(self, user_manager: UserManager, db_file: str = "transactions.json", ledger_file: str = "ledger.json"):
        self.user_manager = user_manager
        self.ledger = LedgerManager()
        
        # Configuration Limits (None currently active)

    def _create_transaction_record(self, sender: str, receiver: str, amount: Decimal, t_type: str, description: str = "", currency: str = "USD", flagged: bool = False, flag_reason: str = "", status: str = "COMPLETED") -> Transaction:
        # Generate a standard reference number (e.g., TXN-12345678-ABCD)
        timestamp_part = int(time.time())
        random_part = str(uuid.uuid4())[:8].upper()
        t_id = f"TXN-{timestamp_part}-{random_part}"
        
        t = Transaction(
            id=t_id, 
            sender_phone=sender, 
            receiver_phone=receiver, 
            amount=amount, 
            currency=currency,
            type=t_type, 
            description=description,
            timestamp=datetime.utcnow().isoformat(),
            status=status,
            flagged=flagged,
            flag_reason=flag_reason
        )
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO transactions (id, sender_phone, receiver_phone, amount, currency, type, timestamp, description, status, flagged, flag_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (t.id, t.sender_phone, t.receiver_phone, str(t.amount), t.currency, t.type, t.timestamp, t.description, t.status, 1 if t.flagged else 0, t.flag_reason))
            conn.commit()
            
        return t

    def get_transaction(self, t_id: str) -> Optional[Transaction]:
        with get_db() as conn:
            conn.row_factory = sqlite3.Row # Ensure rows can be accessed by name
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE id = ?", (t_id,))
            row = cursor.fetchone()
            if row:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                return Transaction.from_dict(t_dict)
        return None

    def admin_adjust_balance(self, phone: str, amount: float, reason: str, is_credit: bool = True) -> Tuple[bool, str]:
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
            
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount"
            
        t_type = "ADMIN_CREDIT" if is_credit else "ADMIN_DEBIT"
        
        # Adjust Balance
        new_balance = user.balance + amount_decimal if is_credit else user.balance - amount_decimal
        if not is_credit and new_balance < 0:
             return False, "Insufficient funds"
            
        # Log Transaction
        self._create_transaction_record(
            sender="ADMIN", 
            receiver=phone, 
            amount=abs(amount_decimal), 
            t_type=t_type, 
            description=reason,
            currency=user.currency
        )
        
        self.user_manager.update_user(phone, balance=new_balance)
        return True, "Balance adjusted successfully."

    def reverse_transaction(self, transaction_id: str) -> Tuple[bool, str]:
        # Find original
        txn = self.get_transaction(transaction_id)
        if not txn:
            return False, "Transaction not found"
            
        if txn.type == "REVERSAL":
            return False, "Cannot reverse a reversal"
            
        # Reverse Logic based on types
        if txn.type in ["TRANSFER", "PAYMENT", "BILL_PAY"]:
             sender = self.user_manager.get_user(txn.sender_phone)
             receiver = self.user_manager.get_user(txn.receiver_phone)
             
             if not sender: return False, "Sender account missing"
             # Receiver might be external (BILL_PAY), handle carefully
             
             # Credit Sender
             sender.balance += txn.amount
             
             # Debit Receiver if internal User
             if receiver:
                 receiver.balance -= txn.amount 
             
             self.user_manager.update_user(sender.phone, balance=sender.balance)
             if receiver:
                 self.user_manager.update_user(receiver.phone, balance=receiver.balance)
             
             # Log Reversal
             self._create_transaction_record(
                 sender=txn.receiver_phone,
                 receiver=txn.sender_phone,
                 amount=txn.amount,
                 t_type="REVERSAL",
                 description=f"Reversal of {txn.id}",
                 currency=txn.currency
             )
             
             with get_db() as conn:
                 cursor = conn.cursor()
                 cursor.execute("UPDATE transactions SET flagged = 1, flag_reason = flag_reason || ' [REVERSED]' WHERE id = ?", (transaction_id,))
                 conn.commit()
                 
             return True, "Transaction reversed."
             
        return False, f"Reversal not implemented for type {txn.type}"

    def _check_limits(self, phone: str, amount: Decimal) -> Tuple[bool, str]:
        # 1. KYC Check
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
            
        if user.status != "active":
            return False, f"Account is {user.status}"

        if not user.is_verified:
            # Maybe allow small deposits? strict: block all.
            return False, "Transaction blocked: KYC Not Verified."
        
        # Risk Tier Limits
        limit = Decimal("5000")
        if user.risk_tier == "low":
            limit = Decimal("1000")
        elif user.risk_tier == "high":
            limit = Decimal("50000")
            
        if amount > limit:
            return False, f"Amount exceeds limit for {user.risk_tier} tier ({limit})"
            
        return True, ""

    def _assess_aml(self, phone: str, amount: Decimal) -> Tuple[bool, str]:
        flagged = False
        reason = []
        
        # 1. Large Transaction
        if amount >= 10000:
            flagged = True
            reason.append("Large amount (>10k)")
            
        # 2. Velocity Check (Rapid Movement)
        now = datetime.utcnow()
        time_window = (now - timedelta(minutes=5)).isoformat()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE sender_phone = ? AND timestamp > ?", (phone, time_window))
            count = cursor.fetchone()[0]
            
        if count >= 5:
            flagged = True
            reason.append("Rapid movement (Velocity)")
            
        return flagged, "; ".join(reason)

    def deposit(self, phone: str, amount: float, description: str = "Deposit") -> Tuple[bool, str]:
        amount_decimal = Decimal(str(amount))
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount_decimal <= 0:
            return False, "Invalid amount"
        
        # Check Limits & KYC
        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
             return False, msg

        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # 1. Create Transaction ID
        txn = self._create_transaction_record(
            sender="SYSTEM", 
            receiver=phone, 
            amount=amount_decimal, 
            t_type="DEPOSIT", 
            description=description,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )

        entries = [
            self.ledger.create_entry(txn.id, "SYSTEM_CASH", -amount_decimal, "Cash In"), # Debit Cash (Asset) - Wait, if we treat + as User Balance Increase (Liability), then Asset Increase should be ... ?
            self.ledger.create_entry(txn.id, phone, amount_decimal, "Deposit to Wallet")
        ]
        
        if self.ledger.post_entries(entries):
            user.balance += amount_decimal
            self.user_manager.update_user(phone, balance=user.balance)
            return True, f"Deposited {amount_decimal} successfully."
        else:
            return False, "Transaction failed: Ledger imbalance."

    def withdraw(self, phone: str, amount: float, description: str = "Withdrawal") -> Tuple[bool, str]:
        amount_decimal = Decimal(str(amount))
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount_decimal <= 0:
            return False, "Invalid amount"
        
        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
            return False, msg

        fee = amount_decimal * Decimal("0.01")
        total_deduction = amount_decimal + fee

        if user.balance < total_deduction:
            return False, f"Insufficient balance."
        
        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # 1. Main Withdrawal
        txn_wd = self._create_transaction_record(
            sender=phone, 
            receiver="SYSTEM", 
            amount=amount_decimal, 
            t_type="WITHDRAWAL", 
            description=description,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        
        entries_wd = [
            self.ledger.create_entry(txn_wd.id, phone, -amount_decimal, "Withdrawal from Wallet"),
            self.ledger.create_entry(txn_wd.id, "SYSTEM_CASH", amount_decimal, "Cash Out")
        ]

        # 2. Fee
        txn_fee = self._create_transaction_record(
            sender=phone, 
            receiver="SYSTEM_REVENUE", 
            amount=fee, 
            t_type="FEE", 
            description=f"Fee: {description}",
            currency=user.currency
        )
        entries_fee = [
            self.ledger.create_entry(txn_fee.id, phone, -fee, "Withdrawal Fee"),
            self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
        ]
        
        if self.ledger.post_entries(entries_wd) and self.ledger.post_entries(entries_fee):
            user.balance -= total_deduction
            self.user_manager.update_user(phone, balance=user.balance)
            return True, f"Withdrawn ${amount_decimal}."
        else:
            return False, "Transaction failed."

    def transfer(self, sender_phone: str, receiver_phone: str, amount: float, description: str = "Transfer") -> Tuple[bool, str]:
        sender = self.user_manager.get_user(sender_phone)
        receiver = self.user_manager.get_user(receiver_phone)

        if not sender:
            return False, "Sender not found"
        if not receiver:
            return False, "Receiver not found"
        if sender_phone == receiver_phone:
            return False, "Cannot transfer to self"
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount"
        
        # Currency check
        if sender.currency != receiver.currency:
            return False, f"Currency mismatch."

        allowed, msg = self._check_limits(sender_phone, amount_decimal)
        if not allowed:
            return False, msg

        fee = amount_decimal * Decimal("0.01")
        total_deduction = amount_decimal + fee

        if sender.balance < total_deduction:
            return False, f"Insufficient balance."

        # AML Check
        flagged, flag_reason = self._assess_aml(sender_phone, amount_decimal)

        # 1. Transfer
        txn_tr = self._create_transaction_record(
            sender=sender_phone, 
            receiver=receiver_phone, 
            amount=amount_decimal, 
            t_type="TRANSFER", 
            description=description,
            currency=sender.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries_tr = [
            self.ledger.create_entry(txn_tr.id, sender_phone, -amount_decimal, "Transfer Out"),
            self.ledger.create_entry(txn_tr.id, receiver_phone, amount_decimal, "Transfer In")
        ]

        # 2. Fee
        txn_fee = self._create_transaction_record(
            sender_phone, 
            "SYSTEM_REVENUE", 
            fee, 
            "FEE", 
            f"Fee for Transfer",
            currency=sender.currency
        )
        entries_fee = [
            self.ledger.create_entry(txn_fee.id, sender_phone, -fee, "Transfer Fee"),
            self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
        ]

        if self.ledger.post_entries(entries_tr) and self.ledger.post_entries(entries_fee):
            sender.balance -= total_deduction
            receiver.balance += amount_decimal
            self.user_manager.update_user(sender_phone, balance=sender.balance)
            self.user_manager.update_user(receiver_phone, balance=receiver.balance)
            return True, "Transfer successful"
        else:
            return False, "Transaction failed"

    def pay_bill(self, phone: str, amount: float, biller_name: str, biller_id: str, description: str = "Bill Payment") -> Tuple[bool, str]:
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
           return False, "Invalid amount"

        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
            return False, msg

        fee = Decimal("0.50")
        total_deduction = amount_decimal + fee
        
        if user.balance < total_deduction:
             return False, f"Insufficient balance."
             
        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # 1. Bill Payment
        full_desc = f"{biller_name} ({biller_id}) - {description}"
        txn_bill = self._create_transaction_record(
            phone, 
            "BILLER_SYSTEM", 
            amount_decimal, 
            "BILL_PAYMENT", 
            full_desc,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries_bill = [
            self.ledger.create_entry(txn_bill.id, phone, -amount_decimal, "Bill Payment"),
            self.ledger.create_entry(txn_bill.id, "BILLER_SYSTEM", amount_decimal, "Bill Payment Received")
        ]
        
        # 2. Fee
        txn_fee = self._create_transaction_record(
            phone, 
            "SYSTEM_REVENUE", 
            fee, 
            "FEE", 
            f"Fee: {biller_name}",
            currency=user.currency
        )
        entries_fee = [
            self.ledger.create_entry(txn_fee.id, phone, -fee, "Bill Fee"),
            self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
        ]
        
        if self.ledger.post_entries(entries_bill) and self.ledger.post_entries(entries_fee):
            user.balance -= total_deduction
            self.user_manager.update_user(phone, balance=user.balance)
            return True, f"Paid {biller_name} successfully."
        else:
            return False, "Transaction Failed"

    def request_money(self, requester_phone: str, payer_phone: str, amount: float, description: str = "Money Request") -> Tuple[bool, str]:
        # Just create a record with PENDING status. No money moves yet.
        requester = self.user_manager.get_user(requester_phone)
        payer = self.user_manager.get_user(payer_phone)
        
        if not requester or not payer:
            return False, "User not found"
        
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount"
            
        t = self._create_transaction_record(
            sender=payer_phone, # Payer will be the sender eventually
            receiver=requester_phone, 
            amount=amount_decimal, 
            t_type="REQUEST", 
            description=description,
            currency=requester.currency, # Use requester's currency preference?? Or payer's? Usually Payer pays in their currency. 
            # But the request is FOR an amount. 
            # Let's assume requester wants their currency.
            status="PENDING"
        )
        
        return True, "Request sent successfully."

    def process_request(self, t_id: str, action: str) -> Tuple[bool, str]: # action = 'PAY' or 'DECLINE'
        # Find transaction
        target_t = self.get_transaction(t_id)
        if not target_t:
            return False, "Request not found"
            
        if target_t.type != "REQUEST" or target_t.status != "PENDING":
            return False, "Invalid request status"
            
        if action == "DECLINE":
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE transactions SET status = 'DECLINED' WHERE id = ?", (t_id,))
                conn.commit()
            return True, "Request declined."
            
        elif action == "PAY":
            # Execute Transfer Logic
            success, msg = self.transfer(target_t.sender_phone, target_t.receiver_phone, float(target_t.amount), target_t.description)
            if success:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE transactions SET status = 'COMPLETED' WHERE id = ?", (t_id,))
                    conn.commit()
                return True, "Request paid successfully."
            else:
                return False, msg
        
        return False, "Invalid action"

    def get_history(self, phone: str) -> List[Transaction]:
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE sender_phone = ? OR receiver_phone = ? ORDER BY timestamp DESC", (phone, phone))
            rows = cursor.fetchall()
            txns = []
            for row in rows:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                txns.append(Transaction.from_dict(t_dict))
            return txns

    @property
    def transactions(self) -> List[Transaction]:
        # Legacy compatibility for parts that iterate over all txns
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions")
            rows = cursor.fetchall()
            txns = []
            for row in rows:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                txns.append(Transaction.from_dict(t_dict))
            return txns
