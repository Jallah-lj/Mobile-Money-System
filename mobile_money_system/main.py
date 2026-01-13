from users import UserManager
from transactions import TransactionManager
import getpass
import os

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    user_manager = UserManager()
    transaction_manager = TransactionManager(user_manager)

    while True:
        print("\n=== Mobile Money System ===")
        print("1. Register")
        print("2. Login")
        print("3. Exit")
        
        choice = input("Select an option: ")

        if choice == '1':
            print("\n--- Register ---")
            phone = input("Enter Phone Number: ")
            name = input("Enter Name: ")
            pin = input("Create PIN (4 digits): ")
            
            print("\n--- Security Setup ---")
            print("Select a Security Question:")
            questions = [
                "What is your mother's maiden name?",
                "What was the name of your first pet?",
                "Which city were you born in?",
                "What is your favorite food?"
            ]
            for i, q in enumerate(questions):
                print(f"{i+1}. {q}")
            
            try:
                q_idx = int(input("Select (1-4): ")) - 1
                if 0 <= q_idx < len(questions):
                    sec_q = questions[q_idx]
                    sec_a = input("Enter Answer: ")
                    
                    success, message = user_manager.register(phone, name, pin, sec_q, sec_a)
                    print(message)
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Invalid input.")

        elif choice == '2':
            print("\n--- Login ---")
            phone = input("Enter Phone Number: ")
            pin = getpass.getpass("Enter PIN: ") # Hides input
            
            user = user_manager.login(phone, pin)
            if user:
                print(f"Welcome, {user.name}!")
                user_session(user, transaction_manager)
            else:
                print("Invalid credentials.")

        elif choice == '3':
            print("Goodbye!")
            break
        else:
            print("Invalid option.")

def user_session(user, transaction_manager):
    while True:
        print(f"\n--- User Menu ({user.name}) ---")
        print("1. Check Balance")
        print("2. Deposit Money")
        print("3. Withdraw Money")
        print("4. Transfer Money")
        print("5. Pay Bill")
        print("6. Inbox / Notifications")
        print("7. Transaction History")
        print("8. Logout")

        choice = input("Select an option: ")

        if choice == '1':
            print(f"Current Balance: ${user.balance:,.2f}")

        elif choice == '2':
            try:
                print("\n--> DEPOSIT FUNDS")
                amount = float(input("Enter amount to deposit: "))
                desc = input("Source/Description (Optional): ")
                
                if amount <= 0:
                    print("Error: Amount must be positive.")
                    continue

                print("\n*** VERIFY DEPOSIT ***")
                print(f"Amount:   ${amount:,.2f}")
                print(f"Ref:      {desc or 'Deposit'}")
                confirm = input("Proceed? (y/n): ")

                if confirm.lower() == 'y':
                    success, message = transaction_manager.deposit(user.phone, amount, desc or "Deposit")
                    print(f"Result: {message}")
                else:
                    print("Transaction cancelled.")

            except ValueError:
                print("Invalid input. Please enter numbers only.")

        elif choice == '3':
            try:
                print("\n--> WITHDRAW FUNDS")
                amount = float(input("Enter amount to withdraw: "))
                desc = input("Purpose/Description (Optional): ")
                
                if amount <= 0:
                    print("Error: Amount must be positive.")
                    continue
                
                fee = amount * 0.01
                total = amount + fee

                print("\n*** VERIFY WITHDRAWAL ***")
                print(f"Amount:   ${amount:,.2f}")
                print(f"Fee (1%): ${fee:,.2f}")
                print(f"Total:    ${total:,.2f}")
                print(f"Ref:      {desc or 'Withdrawal'}")
                confirm = input("Proceed? (y/n): ")

                if confirm.lower() == 'y':
                    success, message = transaction_manager.withdraw(user.phone, amount, desc or "Withdrawal")
                    print(f"Result: {message}")
                else:
                    print("Transaction cancelled.")
            
            except ValueError:
                print("Invalid input.")

        elif choice == '4':
            try:
                print("\n--> SEND MONEY")
                receiver = input("Enter Receiver Phone: ")
                amount = float(input("Enter amount to send: "))
                desc = input("Description: ")
                
                if amount <= 0:
                     print("Error: Amount must be positive.")
                     continue
                
                # Check for receiver existence
                rx_user = transaction_manager.user_manager.get_user(receiver)
                if not rx_user:
                    print("Error: Receiver not found.")
                    continue

                fee = amount * 0.01
                total = amount + fee
                
                print("\n*** VERIFY TRANSFER ***")
                print(f"To:       {rx_user.name} ({receiver})")
                print(f"Amount:   ${amount:,.2f}")
                print(f"Fee (1%): ${fee:,.2f}")
                print(f"Total:    ${total:,.2f}")
                print(f"Ref:      {desc}")
                
                confirm = input("Proceed? (y/n): ")
                
                if confirm.lower() == 'y':
                    success, message = transaction_manager.transfer(user.phone, receiver, amount, desc)
                    print(f"Result: {message}")
                else:
                    print("Transaction cancelled.")

            except ValueError:
                print("Invalid input.")

        elif choice == '5':
            try:
                print("\n--> PAY BILL")
                print("1. Airtime/Data")
                print("2. Electricity")
                print("3. Water")
                
                b_choice = input("Select Service: ")
                service_map = {"1": "Airtime", "2": "Electricity", "3": "Water"}
                
                if b_choice in service_map:
                    service = service_map[b_choice]
                    b_id = input("Enter Account/Meter/Phone Number: ")
                    amount = float(input("Enter Amount: "))
                    
                    fee = 0.50
                    total = amount + fee
                    
                    print(f"\n*** VERIFY BILL PAYMENT ***")
                    print(f"Service:  {service}")
                    print(f"ID:       {b_id}")
                    print(f"Amount:   ${amount:,.2f}")
                    print(f"Fee:      ${fee:,.2f}")
                    print(f"Total:    ${total:,.2f}")
                    
                    confirm = input("Proceed? (y/n): ")
                    if confirm.lower() == 'y':
                        success, message = transaction_manager.pay_bill(user.phone, amount, service, b_id, "Utility Payment")
                        print(f"Result: {message}")
                    else:
                        print("Cancelled.")
                else:
                    print("Invalid service.")
            except ValueError:
                print("Invalid input.")

        elif choice == '6':
            print("\n--> INBOX")
            history = transaction_manager.get_history(user.phone)
            count = 0
            if history:
                for t in reversed(history):
                    if t.type == "TRANSFER" and t.receiver_phone == user.phone:
                        print(f"[*] Received ${t.amount:,.2f} from {t.sender_phone} at {t.timestamp.replace('T', ' ')[:16]}")
                        count += 1
                    elif t.type == "BILL_PAYMENT" and t.sender_phone == user.phone:
                        print(f"[v] Paid Bill ${t.amount:,.2f} for {t.description} at {t.timestamp.replace('T', ' ')[:16]}")
                        count += 1
            
            if count == 0:
                print("No recent notifications.")
            input("\nPress Enter to continue...")

        elif choice == '7':
            print("\n--> TRANSACTION HISTORY")
            history = transaction_manager.get_history(user.phone)
            print(f"{'ID':<10} | {'Type':<12} | {'Amount':<10} | {'Date':<16} | {'Description'}")
            print("-" * 80)
            if history:
                 for t in history:
                    print(f"{t.id:<10} | {t.type:<12} | ${t.amount:<9,.2f} | {t.timestamp.replace('T', ' ')[:16]:<16} | {t.description or t.receiver_phone}")
            else:
                print("No transactions.")
            input("\nPress Enter to continue...")

        elif choice == '8':
            break

if __name__ == "__main__":
    main()
