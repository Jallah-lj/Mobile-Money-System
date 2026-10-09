"""Promote a user to admin.

Usage: python set_admin.py <phone_number>

Works against the SQLite database (mobile_money.db). The phone number is
normalized to E.164 format, matching how users are stored at registration.
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'mobile_money_system')))

from database import get_db, init_db, DB_PATH  # noqa: E402
from users import UserManager  # noqa: E402


def set_admin(phone: str):
    init_db()
    user_manager = UserManager()

    phone_e164 = user_manager.format_phone(phone)
    user = user_manager.get_user(phone_e164) or user_manager.get_user(phone)

    if not user:
        print(f"Error: User with phone {phone} not found in {DB_PATH}.")
        return

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (user.phone,))
        conn.commit()

    print(f"Success: User {user.name} ({user.phone}) is now an Admin.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python set_admin.py <phone_number>")
    else:
        set_admin(sys.argv[1])
