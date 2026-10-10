from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

def utcnow() -> datetime:
    """Timezone-aware UTC now, returned as naive UTC for consistent DB storage.

    Replaces the deprecated ``datetime.utcnow()`` while keeping the exact
    same ISO format already stored in the database (naive UTC), so existing
    rows remain string-comparable with new ones.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

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

    # Security Fields
    two_factor_enabled: bool = True  # OTP required at login / high-value actions

    # Personal finance
    monthly_budget: Decimal = field(default_factory=lambda: Decimal("0"))  # 0 = no budget set

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
            "risk_tier": self.risk_tier,
            "two_factor_enabled": self.two_factor_enabled,
            "monthly_budget": str(self.monthly_budget)
        }

    def to_public_dict(self):
        """Safe representation for API/UI display — no credentials or raw KYC data."""
        d = self.to_dict()
        d.pop("pin", None)
        d.pop("sec_a", None)
        d.pop("sec_q", None)
        if self.id_number:
            d["id_number"] = "****" + self.id_number[-4:]
        return d

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
            risk_tier=data.get("risk_tier", "standard"),
            two_factor_enabled=bool(data.get("two_factor_enabled", True)),
            monthly_budget=Decimal(str(data.get("monthly_budget") or "0"))
        )

@dataclass
class Transaction:
    id: str
    sender_phone: str
    receiver_phone: str
    amount: Decimal
    currency: str
    type: str
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())
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
            timestamp=data.get("timestamp", utcnow().isoformat()),
            description=data.get("description", ""),
            status=data.get("status", "COMPLETED"),
            flagged=bool(data.get("flagged", False)),
            flag_reason=data.get("flag_reason", "")
        )

@dataclass
class AuditEntry:
    """Immutable record of a security-relevant system event."""
    id: str
    timestamp: str
    actor_phone: str   # Who performed the action ('SYSTEM' for automated events)
    action: str        # e.g. LOGIN_SUCCESS, TRANSFER, KYC_SUBMIT
    target: str = ""   # What the action applied to (phone, transaction id, ...)
    details: str = ""
    status: str = "SUCCESS"  # SUCCESS | FAILURE | BLOCKED

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "actor_phone": self.actor_phone,
            "action": self.action,
            "target": self.target,
            "details": self.details,
            "status": self.status
        }

    @staticmethod
    def from_dict(data: dict) -> 'AuditEntry':
        return AuditEntry(
            id=data["id"],
            timestamp=data["timestamp"],
            actor_phone=data["actor_phone"],
            action=data["action"],
            target=data.get("target", ""),
            details=data.get("details", ""),
            status=data.get("status", "SUCCESS")
        )

@dataclass
class LedgerEntry:
    id: str
    transaction_id: str
    account_id: str  # Phone number or System Account (e.g., 'SYSTEM_REVENUE', 'SYSTEM_CASH')
    amount: Decimal # Positive for Credit (Increase User Balance), Negative for Debit (Decrease User Balance)
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())
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
            timestamp=data.get("timestamp", utcnow().isoformat()),
            description=data.get("description", "")
        )

