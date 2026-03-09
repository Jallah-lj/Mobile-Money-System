import os
import sys
import sqlite3

DB_PATH = os.path.join("mobile_money_system", "mobile_money.db")

def set_admin(phone):
    # Search for the database file in the current directory or mobile_money_system/
    db_file = DB_PATH if os.path.exists(DB_PATH) else "mobile_money.db"

    if not os.path.exists(db_file):
        print(f"Error: Database file not found. Run the app first to initialise the database.")
        return

    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        cursor.execute("SELECT phone, name FROM users WHERE phone = ?", (phone,))
        row = cursor.fetchone()

        if not row:
            print(f"Error: User with phone {phone} not found.")
            conn.close()
            return

        cursor.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()

        print(f"Success: User {row[1]} ({phone}) is now an Admin.")

    except Exception as e:
        print(f"Error accessing database: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python set_admin.py <phone_number>")
    else:
        set_admin(sys.argv[1])
