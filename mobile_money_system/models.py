from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
from decimal import Decimal

@dataclass
class User:
    phone: str
    name: str
    pin: str  # In a real system, should be hashed
    balance: Decimal = field(default_factory=lambda: Decimal("0.0"))
    currency: str = "USD"  # Default currency
    role: str = "user"
    sec_q: str = ""
    sec_a: str = ""
    
    # KYC Fields
    id_type: str = "" # passport, national_id
    id_number: str = "" 
    is_verified: bool = False
    
    # Status Fields
    status: str = "active" # active, suspended, deleted
    risk_tier: str = "standard" # low, standard, high

    def to_dict(self):
        return {
            "phone": self.phone,
            "name": self.name,
            "pin": self.pin,
            "balance": str(self.balance),
            "currency": self.currency,
            "role": self.role,
            "sec_q": self.sec_q,
            "sec_a": self.sec_a,
            "id_type": self.id_type,
            "id_number": self.id_number,
            "is_verified": self.is_verified,
            "status": self.status,
            "risk_tier": self.risk_tier
        }

    @staticmethod
    def from_dict(data: dict) -> 'User':
        return User(
            phone=data["phone"],
            name=data["name"],
            pin=data["pin"],
            balance=Decimal(str(data.get("balance", "0.0"))),
            currency=data.get("currency", "USD"),
            role=data.get("role", "user"),
            sec_q=data.get("sec_q", ""),
            sec_a=data.get("sec_a", ""),
            id_type=data.get("id_type", ""),
            id_number=data.get("id_number", ""),
            is_verified=data.get("is_verified", False),
            status=data.get("status", "active"),
            risk_tier=data.get("risk_tier", "standard")
        )

@dataclass
class Transaction:
    id: str
    sender_phone: str
    receiver_phone: str
    amount: Decimal
    currency: str
    type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""
    status: str = "COMPLETED"
    
    # AML Fields
    flagged: bool = False
    flag_reason: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "sender_phone": self.sender_phone,
            "receiver_phone": self.receiver_phone,
            "amount": str(self.amount),
            "currency": self.currency,
            "type": self.type,
            "timestamp": self.timestamp,
            "description": self.description,
            "status": self.status,
            "flagged": self.flagged,
            "flag_reason": self.flag_reason
        }
    
    @staticmethod
    def from_dict(data: dict) -> 'Transaction':
        return Transaction(
            id=data["id"],
            sender_phone=data["sender_phone"],
            receiver_phone=data["receiver_phone"],
            amount=Decimal(str(data["amount"])),
            currency=data.get("currency", "USD"),
            type=data["type"],
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            description=data.get("description", ""),
            status=data.get("status", "COMPLETED"),
            flagged=data.get("flagged", False),
            flag_reason=data.get("flag_reason", "")
        )

@dataclass
class LedgerEntry:
    id: str
    transaction_id: str
    account_id: str  # Phone number or System Account (e.g., 'SYSTEM_REVENUE', 'SYSTEM_CASH')
    amount: Decimal # Positive for Credit (Increase User Balance), Negative for Debit (Decrease User Balance)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "amount": str(self.amount),
            "timestamp": self.timestamp,
            "description": self.description
        }

    @staticmethod
    def from_dict(data: dict) -> 'LedgerEntry':
        return LedgerEntry(
            id=data["id"],
            transaction_id=data["transaction_id"],
            account_id=data["account_id"],
            amount=Decimal(str(data["amount"])),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            description=data.get("description", "")
        )
