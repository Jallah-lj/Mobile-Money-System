import json
import sys

def set_admin(phone):
    db_file = "users.json"
    
    # Try looking in 'mobile_money_system' if not in root
    if not os.path.exists(db_file):
        db_file = os.path.join("mobile_money_system", "users.json")
    
    if not os.path.exists(db_file):
        print(f"Error: {db_file} not found.")
        return

    try:
        with open(db_file, "r") as f:
            users = json.load(f)
        
        if phone not in users:
            print(f"Error: User with phone {phone} not found.")
            return
            
        users[phone]["role"] = "admin"
        
        with open(db_file, "w") as f:
            json.dump(users, f, indent=4)
            
        print(f"Success: User {users[phone]['name']} ({phone}) is now an Admin.")
        
    except Exception as e:
        print(f"Error accessing database: {e}")

if __name__ == "__main__":
    import os
    if len(sys.argv) != 2:
        print("Usage: python set_admin.py <phone_number>")
    else:
        set_admin(sys.argv[1])
