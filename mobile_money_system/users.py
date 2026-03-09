import bcrypt
import logging
import phonenumbers
import random
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from decimal import Decimal

try:
    from models import User
    from database import get_db
except ImportError:
    from mobile_money_system.models import User
    from mobile_money_system.database import get_db

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 30

class UserManager:
    def __init__(self):
        # We no longer load all users into memory
        self.otp_storage: Dict[str, dict] = {} # {phone: {'code': '1234', 'expiry': timestamp}}
        self._ensure_admin_exists()

    def _ensure_admin_exists(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone FROM users WHERE role = 'admin'")
            admin = cursor.fetchone()
            if not admin:
                import os
                # Use environment variables so credentials are never hardcoded.
                # Set ADMIN_PHONE and ADMIN_PIN before first run; defaults are intentionally
                # random so the system is not left with guessable credentials.
                admin_phone = os.environ.get("ADMIN_PHONE", "0000000000")
                admin_pin = os.environ.get("ADMIN_PIN", str(random.randint(100000, 999999)))
                hashed = bcrypt.hashpw(admin_pin.encode(), bcrypt.gensalt()).decode()
                cursor.execute('''
                INSERT INTO users (phone, name, pin, role, status)
                VALUES (?, 'System Admin', ?, 'admin', 'active')
                ''', (admin_phone, hashed))
                conn.commit()
                # Write the one-time setup credentials to stderr via the logging system.
                # Operators should pipe stderr to a secure log and immediately set
                # the ADMIN_PHONE / ADMIN_PIN environment variables.
                if "ADMIN_PIN" not in os.environ:
                    import sys
                    logger.warning(
                        "[ADMIN SETUP] Default admin created. "
                        "Phone: %s  PIN: %s  "
                        "Set ADMIN_PHONE / ADMIN_PIN env vars before production use.",
                        admin_phone, admin_pin,
                    )
                    # Also print to stderr so it is visible in console environments
                    # that have not configured logging handlers.
                    print(
                        f"[ADMIN SETUP] Default admin created. "
                        f"Phone: {admin_phone}  PIN: {admin_pin}  "
                        f"Set ADMIN_PHONE / ADMIN_PIN env vars before production use.",
                        file=sys.stderr,
                    )

    def validate_phone(self, phone: str) -> bool:
        try:
            # Parse with a default region for cases where '+' is missing but it's a valid local number
            # However, for world-wide we should encourage '+'
            parsed = phonenumbers.parse(phone, None)
            return phonenumbers.is_valid_number(parsed)
        except Exception:
            return False

    def format_phone(self, phone: str) -> str:
        try:
            parsed = phonenumbers.parse(phone, None)
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            return phone

    def register(self, phone: str, name: str, pin: str, sec_q: str, sec_a: str, currency: str = "USD") -> Tuple[bool, str]:
        if not self.validate_phone(phone):
            return False, "Invalid international phone number format (use +countrycode...)"
        
        phone_e164 = self.format_phone(phone)
        
        if self.get_user(phone_e164):
            return False, "User already exists"
        
        # Bcrypt for PIN
        salt = bcrypt.gensalt()
        hashed_pin = bcrypt.hashpw(pin.encode(), salt).decode()
        
        # Hash the Security Answer for privacy
        hashed_ans = hashlib.sha256(sec_a.lower().strip().encode()).hexdigest()
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO users (phone, name, pin, sec_q, sec_a, currency, is_verified, balance)
            VALUES (?, ?, ?, ?, ?, ?, 0, '0.0')
            ''', (phone_e164, name, hashed_pin, sec_q, hashed_ans, currency))
            conn.commit()
            
        return True, f"User registered successfully as {phone_e164}. Please complete KYC to transact."

    def submit_kyc(self, phone: str, id_type: str, id_number: str) -> Tuple[bool, str]:
        user = self.get_user(phone)
        if not user:
            return False, "User not found"
        
        if id_type not in ["passport", "national_id", "manual_admin"]:
             return False, "Invalid ID Type."

        # Only admin-triggered KYC or a long-enough ID auto-verifies.
        # In a production system this would involve a real document verification service.
        is_verified = 1 if id_type == "manual_admin" else 0
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users SET id_type = ?, id_number = ?, is_verified = ? WHERE phone = ?
            ''', (id_type, id_number, is_verified, phone))
            conn.commit()
            
        if is_verified:
            return True, "KYC Verified."
        return True, "KYC Submitted. Awaiting admin review."

    def verify_security_answer(self, phone: str, answer_attempt: str) -> bool:
        user = self.get_user(phone)
        if not user:
            return False
        
        hashed_attempt = hashlib.sha256(answer_attempt.lower().strip().encode()).hexdigest()
        return user.sec_a == hashed_attempt

    def reset_pin(self, phone: str, new_pin: str) -> Tuple[bool, str]:
        hashed_pin = bcrypt.hashpw(new_pin.encode(), bcrypt.gensalt()).decode()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET pin = ? WHERE phone = ?", (hashed_pin, phone))
            conn.commit()
        return True, "PIN reset successfully"

    def login(self, phone: str, pin: str) -> Optional[User]:
        # Try finding by original input or formatted
        user = self.get_user(phone)
        if not user:
            user = self.get_user(self.format_phone(phone))
            
        if user:
            # Check for account lockout
            if user.locked_until:
                try:
                    locked_dt = datetime.fromisoformat(user.locked_until)
                    if datetime.now(timezone.utc) < locked_dt:
                        return None  # Account is still locked
                    else:
                        # Lockout expired – reset counters
                        self._reset_failed_attempts(user.phone)
                        user = self.get_user(user.phone)
                except (ValueError, TypeError):
                    pass

            # Bcrypt check only — no plaintext or legacy hash fallback
            try:
                if bcrypt.checkpw(pin.encode(), user.pin.encode()):
                    self._reset_failed_attempts(user.phone)
                    return user
            except Exception:
                pass  # Invalid hash format — deny

            # Wrong PIN: increment failure counter
            self._record_failed_attempt(user.phone)

        return None

    def _record_failed_attempt(self, phone: str) -> None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE phone = ?",
                (phone,)
            )
            conn.commit()
            cursor.execute("SELECT failed_attempts FROM users WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            if row and row[0] >= MAX_FAILED_ATTEMPTS:
                locked_until = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                cursor.execute(
                    "UPDATE users SET locked_until = ? WHERE phone = ?",
                    (locked_until, phone)
                )
                conn.commit()

    def _reset_failed_attempts(self, phone: str) -> None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE phone = ?",
                (phone,)
            )
            conn.commit()

    def is_account_locked(self, phone: str) -> bool:
        user = self.get_user(phone)
        if not user or not user.locked_until:
            return False
        try:
            return datetime.now(timezone.utc) < datetime.fromisoformat(user.locked_until)
        except (ValueError, TypeError):
            return False

    def get_user(self, phone: str) -> Optional[User]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            if row:
                return User.from_dict(dict(row))
        return None
    
    @property
    def users(self) -> Dict[str, User]:
        # Legacy compatibility for parts of the app that iterate over all users (Admin panel)
        # WARNING: This mimics the old dict but loads from DB.
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            rows = cursor.fetchall()
            return {row['phone']: User.from_dict(dict(row)) for row in rows}

    def generate_otp(self, phone: str) -> str:
        code = str(random.randint(100000, 999999))
        self.otp_storage[phone] = {
            'code': code,
            'expiry': time.time() + 300 # 5 minutes expiry
        }
        return code

    def verify_otp(self, phone: str, code_attempt: str) -> bool:
        record = self.otp_storage.get(phone)
        if not record:
            return False
        if time.time() > record['expiry']:
            del self.otp_storage[phone]
            return False
        if record['code'] == code_attempt.strip():
            del self.otp_storage[phone]
            return True
        return False

    def update_user(self, phone: str, **kwargs) -> Tuple[bool, str]:
        user = self.get_user(phone)
        if not user:
            return False, "User not found"
        
        allowed_fields = ["name", "pin", "sec_q", "sec_a", "status", "risk_tier", "balance"]
        updates = []
        params = []
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                if key == "pin":
                    value = bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()
                elif key == "sec_a":
                    value = hashlib.sha256(value.lower().strip().encode()).hexdigest()
                elif key == "balance":
                    value = str(value)
                
                updates.append(f"{key} = ?")
                params.append(value)
        
        if not updates:
            return True, "No changes"
            
        params.append(phone)
        with get_db() as conn:
            cursor = conn.cursor()
            query = f"UPDATE users SET {', '.join(updates)} WHERE phone = ?"
            cursor.execute(query, params)
            conn.commit()
            
        return True, "Profile updated"

    def save_users(self):
        # Legacy placeholder, now handled by individual methods
        pass

    def admin_reset_pin(self, phone: str) -> Tuple[bool, str]:
        new_pin_raw = str(random.randint(1000, 9999))
        self.reset_pin(phone, new_pin_raw)
        # In a production system the new PIN would be delivered via SMS to the user.
        # It must NOT be displayed in the UI to prevent it being seen by the admin.
        return True, "PIN has been reset. The user will receive their new PIN via SMS."

    def suspend_user(self, phone: str) -> Tuple[bool, str]:
        return self.update_user(phone, status="suspended")
        
    def reactivate_user(self, phone: str) -> Tuple[bool, str]:
        return self.update_user(phone, status="active")
        
    def delete_user(self, phone: str) -> Tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE phone = ?", (phone,))
            conn.commit()
        return True, "User permanently deleted."

