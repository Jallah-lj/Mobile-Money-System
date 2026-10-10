import bcrypt
import phonenumbers
import random
import time
import hashlib
from typing import Dict, List, Optional, Tuple
from decimal import Decimal

try:
    from models import User, utcnow
    from database import get_db, init_db
    from audit import log_event
except ImportError:
    from mobile_money_system.models import User, utcnow
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.audit import log_event

# --- Login protection configuration ---
MAX_LOGIN_ATTEMPTS = 5          # Failed attempts before lockout
LOCKOUT_WINDOW_SECONDS = 15 * 60  # Only failures inside this window count
LOCKOUT_DURATION_SECONDS = 15 * 60  # How long the lockout lasts

# --- Step-up authentication -------------------------------------------------
# Debit transactions above this amount require a fresh OTP even when the user
# is already logged in (protects against session hijacking of large transfers).
HIGH_VALUE_STEPUP_THRESHOLD = 1000  # USD

class UserManager:
    def __init__(self):
        # We no longer load all users into memory
        self.otp_storage: Dict[str, dict] = {} # {phone: {'code': '1234', 'expiry': timestamp}}
        self._failed_logins: Dict[str, List[float]] = {}  # {phone: [timestamps of failures]}
        self._locked_until: Dict[str, float] = {}         # {phone: unix ts until which login is blocked}
        init_db()  # Ensure schema exists (safe on fresh databases)
        self._ensure_admin_exists()

    def _ensure_admin_exists(self):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone FROM users WHERE role = 'admin'")
            admin = cursor.fetchone()
            if not admin:
                # Create Default Admin (0000000000)
                # Password is 'admin123'
                hashed = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
                cursor.execute('''
                INSERT INTO users (phone, name, pin, role, status)
                VALUES ('0000000000', 'System Admin', ?, 'admin', 'active')
                ''', (hashed,))
                conn.commit()

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
            
        log_event(phone_e164, "REGISTER", target=phone_e164, details=f"New user registered: {name}")
        return True, f"User registered successfully as {phone_e164}. Please complete KYC to transact."

    def submit_kyc(self, phone: str, id_type: str, id_number: str) -> Tuple[bool, str]:
        user = self.get_user(phone)
        if not user:
            return False, "User not found"
        
        if id_type not in ["passport", "national_id", "manual_admin"]:
             return False, "Invalid ID Type."
        
        is_verified = 1 if (len(id_number) > 5 or id_type == "manual_admin") else 0
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE users SET id_type = ?, id_number = ?, is_verified = ? WHERE phone = ?
            ''', (id_type, id_number, is_verified, phone))
            conn.commit()
            
        log_event(phone, "KYC_SUBMIT", target=phone,
                  details=f"id_type={id_type} verified={bool(is_verified)}",
                  status="SUCCESS" if is_verified else "FAILURE")
        return True, "KYC Updated." if is_verified else "KYC Submitted (Rejected: ID too short)."

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
        log_event(phone, "PIN_RESET", target=phone, details="PIN was reset")
        return True, "PIN reset successfully"

    # --- Login rate limiting / lockout -------------------------------------

    def is_locked_out(self, phone: str) -> Tuple[bool, int]:
        """Returns (locked, seconds_remaining) for the given phone."""
        key = self.format_phone(phone)
        until = self._locked_until.get(key, 0)
        if until and time.time() < until:
            return True, int(until - time.time())
        if until:
            # Lockout expired — clean up
            del self._locked_until[key]
        return False, 0

    def _record_failed_login(self, phone: str):
        key = self.format_phone(phone)
        now = time.time()
        failures = [t for t in self._failed_logins.get(key, [])
                    if now - t <= LOCKOUT_WINDOW_SECONDS]
        failures.append(now)
        self._failed_logins[key] = failures
        if len(failures) >= MAX_LOGIN_ATTEMPTS:
            self._locked_until[key] = now + LOCKOUT_DURATION_SECONDS
            del self._failed_logins[key]
            log_event(key, "ACCOUNT_LOCKED", target=key,
                      details=f"Locked out after {MAX_LOGIN_ATTEMPTS} failed attempts",
                      status="BLOCKED")

    def _clear_failed_logins(self, phone: str):
        key = self.format_phone(phone)
        self._failed_logins.pop(key, None)
        self._locked_until.pop(key, None)

    def login(self, phone: str, pin: str) -> Optional[User]:
        # --- Brute-force protection ---
        locked, remaining = self.is_locked_out(phone)
        if locked:
            log_event(self.format_phone(phone), "LOGIN_FAILURE", target=phone,
                      details=f"Attempt during lockout ({remaining}s remaining)", status="BLOCKED")
            return None

        # Try finding by original input or formatted
        user = self.get_user(phone)
        if not user:
            user = self.get_user(self.format_phone(phone))
            
        if user:
            # Bcrypt check
            try:
                if bcrypt.checkpw(pin.encode(), user.pin.encode()):
                    self._clear_failed_logins(phone)
                    log_event(user.phone, "LOGIN_SUCCESS", target=user.phone)
                    return user
            except Exception:
                # Fallback for old SHA256 or Plaintext from migration if any (unlikely with new logic but safe)
                if user.pin == hashlib.sha256(pin.encode()).hexdigest() or user.pin == pin:
                    # Upgrade to bcrypt immediately
                    self.reset_pin(user.phone, pin)
                    self._clear_failed_logins(phone)
                    log_event(user.phone, "LOGIN_SUCCESS", target=user.phone,
                              details="Legacy PIN hash upgraded to bcrypt")
                    return user
                    
        self._record_failed_login(phone)
        log_event(self.format_phone(phone), "LOGIN_FAILURE", target=phone,
                  details="Invalid credentials", status="FAILURE")
        return None

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
        """Verify a one-time passcode. Only codes issued by generate_otp are valid."""
        record = self.otp_storage.get(phone)
        if not record:
            return False
        if time.time() > record['expiry']:
            del self.otp_storage[phone]
            return False
        if record['code'] == code_attempt.strip():
            del self.otp_storage[phone]
            log_event(phone, "OTP_VERIFIED", target=phone)
            return True
        log_event(phone, "OTP_FAILURE", target=phone, status="FAILURE",
                  details="Invalid OTP code submitted")
        return False

    def set_two_factor(self, phone: str, enabled: bool) -> Tuple[bool, str]:
        """Enable/disable OTP-based two-factor authentication for the account."""
        user = self.get_user(phone)
        if not user:
            return False, "User not found"
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET two_factor_enabled = ? WHERE phone = ?",
                           (1 if enabled else 0, phone))
            conn.commit()
        log_event(phone, "2FA_ENABLED" if enabled else "2FA_DISABLED", target=phone,
                  details=f"Two-factor authentication {'enabled' if enabled else 'disabled'} by user")
        return True, f"Two-factor authentication {'enabled' if enabled else 'disabled'}."

    def update_user(self, phone: str, **kwargs) -> Tuple[bool, str]:
        user = self.get_user(phone)
        if not user:
            return False, "User not found"

        allowed_fields = ["name", "pin", "sec_q", "sec_a", "status", "risk_tier", "balance",
                          "two_factor_enabled", "monthly_budget"]
        updates = []
        params = []
        
        for key, value in kwargs.items():
            if key in allowed_fields:
                if value is None:
                    continue  # None means "leave unchanged"
                if key == "pin":
                    value = bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()
                elif key == "sec_a":
                    value = hashlib.sha256(value.lower().strip().encode()).hexdigest()
                elif key == "balance":
                    value = str(value)
                elif key == "monthly_budget":
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
        log_event("ADMIN", "ADMIN_PIN_RESET", target=phone, details=f"Admin reset PIN for {phone}")
        return True, f"PIN reset to: {new_pin_raw}"

    def suspend_user(self, phone: str) -> Tuple[bool, str]:
        result = self.update_user(phone, status="suspended")
        log_event("ADMIN", "USER_SUSPENDED", target=phone)
        return result
        
    def reactivate_user(self, phone: str) -> Tuple[bool, str]:
        result = self.update_user(phone, status="active")
        log_event("ADMIN", "USER_REACTIVATED", target=phone)
        return result
        
    def delete_user(self, phone: str) -> Tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE phone = ?", (phone,))
            conn.commit()
        log_event("ADMIN", "USER_DELETED", target=phone)
        return True, "User permanently deleted."

