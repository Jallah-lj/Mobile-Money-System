import hashlib
import random
import time
from typing import Dict, Optional, Tuple

try:
    from models import User
    from storage import JsonStorage
except ImportError:
    from mobile_money_system.models import User
    from mobile_money_system.storage import JsonStorage

class UserManager:
    def __init__(self, db_file: str = "users.json"):
        self.storage = JsonStorage(db_file)
        self.users: Dict[str, User] = {}
        self.otp_storage: Dict[str, dict] = {} # {phone: {'code': '1234', 'expiry': timestamp}}
        self.load_users()

    def load_users(self):
        data = self.storage.load(default={})
        self.users = {}
        # Handle case where file might be empty or valid json but not dict
        if isinstance(data, dict):
            for phone, user_data in data.items():
                self.users[phone] = User.from_dict(user_data)
        
        # Create Default Admin if not exists
        if "0000000000" not in self.users:
            admin_pin = hashlib.sha256("admin123".encode()).hexdigest()
            self.users["0000000000"] = User(
                phone="0000000000",
                name="System Admin",
                pin=admin_pin,
                role="admin"
            )
            self.save_users()

    def save_users(self):
        data = {phone: user.to_dict() for phone, user in self.users.items()}
        self.storage.save(data)

    def register(self, phone: str, name: str, pin: str, sec_q: str, sec_a: str, currency: str = "USD") -> Tuple[bool, str]:
        if phone in self.users:
            return False, "User already exists"
        
        # Hash the PIN before storing
        hashed_pin = hashlib.sha256(pin.encode()).hexdigest()
        # Hash the Security Answer for privacy
        hashed_ans = hashlib.sha256(sec_a.lower().strip().encode()).hexdigest()
        
        new_user = User(
            phone=phone,
            name=name,
            pin=hashed_pin,
            sec_q=sec_q,
            sec_a=hashed_ans,
            currency=currency,
            is_verified=False # Requires KYC
        )
        self.users[phone] = new_user
        self.save_users()
        return True, "User registered successfully. Please complete KYC to transact."

    def submit_kyc(self, phone: str, id_type: str, id_number: str) -> Tuple[bool, str]:
        user = self.users.get(phone)
        if not user:
            return False, "User not found"
        
        if id_type not in ["passport", "national_id"]:
             return False, "Invalid ID Type. Must be 'passport' or 'national_id'"
        
        user.id_type = id_type
        user.id_number = id_number
        # specific logic: In a real app this would go to pending. 
        # For this prototype we'll verify immediately if ID number > 5 chars.
        if len(id_number) > 5:
            user.is_verified = True
            msg = "KYC Verified successfully."
        else:
            user.is_verified = False
            msg = "KYC Submitted but rejected (ID too short)."
            
        self.save_users()
        return True, msg

    def verify_security_answer(self, phone: str, answer_attempt: str) -> bool:
        user = self.users.get(phone)
        if not user:
            return False
        
        hashed_attempt = hashlib.sha256(answer_attempt.lower().strip().encode()).hexdigest()
        return user.sec_a == hashed_attempt

    def reset_pin(self, phone: str, new_pin: str) -> Tuple[bool, str]:
        user = self.users.get(phone)
        if not user:
            return False, "User not found"
            
        hashed_pin = hashlib.sha256(new_pin.encode()).hexdigest()
        user.pin = hashed_pin
        self.save_users()
        return True, "PIN reset successfully"

    def login(self, phone: str, pin: str) -> Optional[User]:
        user = self.users.get(phone)
        if user:
            # Check hashed pin
            hashed_input = hashlib.sha256(pin.encode()).hexdigest()
            # Fallback for old plain text pins (optional, but good for dev)
            if user.pin == hashed_input or user.pin == pin:
                 return user
        return None

    def get_user(self, phone: str) -> Optional[User]:
        return self.users.get(phone)
    
    def generate_otp(self, phone: str) -> str:
        code = str(random.randint(100000, 999999))
        self.otp_storage[phone] = {
            'code': code,
            'expiry': time.time() + 300 # 5 minutes expiry
        }
        return code

    def verify_otp(self, phone: str, code_attempt: str) -> bool:
        # Master Code for Testing/Development
        if code_attempt == "123456":
            return True

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

    def update_user(self, phone: str, name: str = None, pin: str = None, sec_q: str = None, sec_a: str = None, status: str = None, risk_tier: str = None) -> Tuple[bool, str]:
        if phone not in self.users:
            return False, "User not found"
        
        user = self.users[phone]
        if name:
            user.name = name
        if pin:
             # Hash the PIN before storing
            hashed_pin = hashlib.sha256(pin.encode()).hexdigest()
            user.pin = hashed_pin
        
        if sec_q and sec_a:
            user.sec_q = sec_q
            # Hash the answer
            hashed_ans = hashlib.sha256(sec_a.lower().strip().encode()).hexdigest()
            user.sec_a = hashed_ans
            
        if status:
            if status not in ["active", "suspended", "deleted"]:
                return False, "Invalid status"
            user.status = status
            
        if risk_tier:
            if risk_tier not in ["low", "standard", "high"]:
                return False, "Invalid risk tier"
            user.risk_tier = risk_tier
            
        self.save_users()
        return True, "Profile updated successfully"

    def admin_reset_pin(self, phone: str) -> Tuple[bool, str]:
        user = self.users.get(phone)
        if not user:
            return False, "User not found"
        
        # Determine strictness of this action
        # For prototype, we generate a random 4 digit pin
        new_pin_raw = str(random.randint(1000, 9999))
        hashed_pin = hashlib.sha256(new_pin_raw.encode()).hexdigest()
        user.pin = hashed_pin
        self.save_users()
        return True, f"PIN reset to: {new_pin_raw}"

    def suspend_user(self, phone: str) -> Tuple[bool, str]:
        return self.update_user(phone, status="suspended")
        
    def reactivate_user(self, phone: str) -> Tuple[bool, str]:
        return self.update_user(phone, status="active")
        
    def delete_user(self, phone: str) -> Tuple[bool, str]:
        # Soft delete is better, but user asked for "permanently delete" options.
        # For safety/audit, I will do SOFT delete (status=deleted) generally, 
        # but if explicit delete is requested:
        if phone not in self.users:
            return False, "User not found"
            
        # Hard delete from dictionary
        del self.users[phone]
        self.save_users()
        return True, "User permanently deleted."
