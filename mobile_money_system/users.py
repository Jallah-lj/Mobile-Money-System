import json
import os
import hashlib

class User:
    def __init__(self, phone, name, pin, balance=0.0, role="user", sec_q="", sec_a=""):
        self.phone = phone
        self.name = name
        self.pin = pin
        self.balance = balance
        self.role = role
        self.sec_q = sec_q # Security Question
        self.sec_a = sec_a # Security Answer

    def to_dict(self):
        return {
            "phone": self.phone,
            "name": self.name,
            "pin": self.pin,
            "balance": self.balance,
            "role": self.role,
            "sec_q": self.sec_q,
            "sec_a": self.sec_a
        }

    @staticmethod
    def from_dict(data):
        return User(
            data["phone"], 
            data["name"], 
            data["pin"], 
            data["balance"],
            role=data.get("role", "user"),
            sec_q=data.get("sec_q", ""),
            sec_a=data.get("sec_a", "")
        )

class UserManager:
    def __init__(self, db_file="users.json"):
        self.db_file = db_file
        self.users = {}
        self.load_users()

    def load_users(self):
        if os.path.exists(self.db_file):
            with open(self.db_file, 'r') as f:
                try:
                    data = json.load(f)
                    for phone, user_data in data.items():
                        self.users[phone] = User.from_dict(user_data)
                except json.JSONDecodeError:
                    self.users = {}
        
        # Create Default Admin if not exists
        if "0000000000" not in self.users:
            admin_pin = hashlib.sha256("admin123".encode()).hexdigest()
            self.users["0000000000"] = User("0000000000", "System Admin", admin_pin, role="admin")
            self.save_users()

    def save_users(self):
        data = {phone: user.to_dict() for phone, user in self.users.items()}
        with open(self.db_file, 'w') as f:
            json.dump(data, f, indent=4)

    def register(self, phone, name, pin, sec_q, sec_a):
        if phone in self.users:
            return False, "User already exists"
        
        # Hash the PIN before storing
        hashed_pin = hashlib.sha256(pin.encode()).hexdigest()
        # Hash the Security Answer for privacy
        hashed_ans = hashlib.sha256(sec_a.lower().strip().encode()).hexdigest()
        
        new_user = User(phone, name, hashed_pin, sec_q=sec_q, sec_a=hashed_ans)
        self.users[phone] = new_user
        self.save_users()
        return True, "User registered successfully"

    def verify_security_answer(self, phone, answer_attempt):
        user = self.users.get(phone)
        if not user:
            return False
        
        hashed_attempt = hashlib.sha256(answer_attempt.lower().strip().encode()).hexdigest()
        return user.sec_a == hashed_attempt

    def reset_pin(self, phone, new_pin):
        user = self.users.get(phone)
        if not user:
            return False, "User not found"
            
        hashed_pin = hashlib.sha256(new_pin.encode()).hexdigest()
        user.pin = hashed_pin
        self.save_users()
        return True, "PIN reset successfully"

    def login(self, phone, pin):
        user = self.users.get(phone)
        if hasattr(user, 'pin'):
            # Check hashed pin
            hashed_input = hashlib.sha256(pin.encode()).hexdigest()
            # Fallback for old plain text pins (optional, but good for dev)
            if user.pin == hashed_input or user.pin == pin:
                 return user
        return None

    def get_user(self, phone):
        return self.users.get(phone)

    def update_user(self, phone, name=None, pin=None, sec_q=None, sec_a=None):
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
            
        self.save_users()
        return True, "Profile updated successfully"
