# Mobile Money System

A comprehensive Mobile Money simulation built with Python and Streamlit. This application mimics a real-world fintech platform with features for users and administrators.

## 📱 Features

### User Features
- **Secure Authentication**: Login with Phone and PIN.
- **Registration**: Sign up with improved security (Security Questions).
- **Send Money**: Transfer funds to other users with a verification review screen.
- **Pay Bills**: Pay for Utilities (Electricity, Water) and Airtime with confirmation.
- **Load Money**: Simulate funding your wallet from a connected bank card.
- **Withdraw**: Withdraw funds with automatic fee calculation.
- **Transaction History**: Detailed history view with downloadable receipts.
- **Inbox**: Real-time notifications for received funds and bill payments.
- **Security**: SHA-256 Hashing for PINs.

### Admin Features
- **Dashboard**: View system-wide metrics (Total Users, Liquidity, Revenue).
- **User Directory**: List all registered users and their balances.
- **Transaction Logs**: Audit trail of every transaction in the system.

## ⚙️ System Controls
- **Transaction Limits**: None
- **Fees**:
  - Transfers: 1%
  - Withdrawals: 1%
  - Bill Payments: $0.50 (Flat Fee)

## 🚀 How to Run

1. **Install Dependencies**:
   ```bash
   pip install -r mobile_money_system/requirements.txt
   ```

2. **Run the Application**:
   ```bash
   streamlit run mobile_money_system/app.py
   ```

3. **Access the App**:
   - The app will open in your browser (usually at http://localhost:8501).

## 🛠️ Setup & Utilities

- **Creating an Admin**:
  The system uses a `users.json` file. To promote a user to Admin, you can use the helper script (if provided) or manually edit the JSON file to set `"role": "admin"` for a specific user.

## 📂 Project Structure
- `app.py`: Main Streamlit web application.
- `transactions.py`: Core logic for financial operations, limits, and fees.
- `users.py`: User management and authentication logic.
- `data/*.json`: Data persistence for Users and Transactions.
