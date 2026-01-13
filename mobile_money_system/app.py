import streamlit as st
from streamlit_option_menu import option_menu
from users import UserManager
from transactions import TransactionManager
import time
import re

def validate_phone(phone):
    return re.match(r'^\d{10,15}$', phone)

# --- Configuration & Styles ---
st.set_page_config(
    page_title="Mobile Money System", 
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load FontAwesome for advanced icons
st.markdown("""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
<style>
    /* Global Styles */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Card Styles */
    .metric-card {
        background-color: #ffffff;
        border-left: 5px solid #4CAF50;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        text-align: center;
        transition: transform 0.2s;
        margin-bottom: 10px;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    .metric-title {
        color: #757575;
        font-size: 0.9em;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .metric-value {
        font-size: 2em;
        font-weight: bold;
        color: #333;
    }

    /* Button Styles */
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 3em;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    .stButton>button:active {
        transform: scale(0.98);
    }

    /* Mobile Responsiveness */
    @media (max-width: 768px) {
        /* Larger touch targets for mobile */
        .stButton>button {
            height: 3.5em; 
            font-size: 1rem;
        }
        
        /* Adjust font sizes */
        .metric-value {
            font-size: 1.8em;
        }
        
        /* Confirmation Card Responsive */
        .conf-card {
            padding: 15px !important;
        }
        .conf-amount {
            font-size: 1.5em !important;
        }
        .conf-label {
            font-size: 0.85em !important;
        }
        
        /* Improve spacing */
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
    
    /* Utility Classes for Cards */
    .conf-card {
        background-color: white; 
        padding: 20px; 
        border-radius: 10px; 
        box-shadow: 0 2px 10px rgba(0,0,0,0.05); 
        border: 1px solid #eee;
    }
    .conf-label {
        color: gray; 
        font-size: 0.9em; 
        text-transform: uppercase;
    }
    .conf-amount {
        font-size: 1.8em; 
        font-weight: bold; 
        color: #333;
    }
</style>
""", unsafe_allow_html=True)

# --- State Management ---
if 'user_manager' not in st.session_state:
    st.session_state.user_manager = UserManager()

if 'transaction_manager' not in st.session_state:
    st.session_state.transaction_manager = TransactionManager(st.session_state.user_manager)

if 'current_user_phone' not in st.session_state:
    st.session_state.current_user_phone = None

user_manager = st.session_state.user_manager
transaction_manager = st.session_state.transaction_manager

# Refresh user object from manager to get latest balance
current_user = None
if st.session_state.current_user_phone:
    current_user = user_manager.get_user(st.session_state.current_user_phone)

# --- Helper Functions ---
def login_user(phone, pin):
    user = user_manager.login(phone, pin)
    if user:
        st.session_state.current_user_phone = user.phone
        st.success(f"Welcome back, {user.name}!")
        time.sleep(0.5)
        st.rerun()
    else:
        st.error("Invalid Phone Number or PIN")

def logout_user():
    st.session_state.current_user_phone = None
    st.rerun()

# --- Application Layout ---

st.markdown("""
<style>
@media (max-width: 768px) {
    .app-title {
        font-size: 1.8rem !important;
    }
}
</style>
<h1 class="app-title" style="text-align: center; color: #4CAF50;"><i class="fa-solid fa-money-bill-transfer"></i> Mobile Money System</h1>
""", unsafe_allow_html=True)

if not current_user:
    # --- Auth View ---
    st.markdown("<h3 style='text-align: center; margin-bottom: 2rem;'>Secure & Fast Mobile Payments</h3>", unsafe_allow_html=True)
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        selected = option_menu(
            menu_title=None,
            options=["Login", "Register"],
            icons=["box-arrow-in-right", "person-plus"],
            menu_icon="cast",
            default_index=0,
            orientation="horizontal",
        )
        
        if selected == "Login":
            with st.form("login_form"):
                st.markdown("### <i class='fa-solid fa-lock'></i> Access Account", unsafe_allow_html=True)
                phone = st.text_input("Phone Number", placeholder="077xxxxxxx")
                pin = st.text_input("PIN", type="password", placeholder="****")
                submitted = st.form_submit_button("Login")
                if submitted:
                    if phone and pin:
                        login_user(phone, pin)
                    else:
                        st.warning("Please enter both Phone and PIN")
            
            # Forgot PIN Feature
            with st.expander("Forgot PIN?"):
                st.markdown("### Reset PIN")
                fp_phone = st.text_input("Enter Phone Number", key="fp_phone")
                
                # Check if user exists to prompt question
                if fp_phone:
                    u_check = user_manager.get_user(fp_phone)
                    if u_check:
                         st.info(f"Security Question: **{u_check.sec_q}**")
                         fp_ans = st.text_input("Your Answer", key="fp_ans")
                         fp_new_pin = st.text_input("New PIN (4 digits)", type="password", max_chars=4, key="fp_new_pin")
                         
                         if st.button("Reset PIN"):
                             if user_manager.verify_security_answer(fp_phone, fp_ans):
                                 if len(fp_new_pin) == 4 and fp_new_pin.isdigit():
                                     user_manager.reset_pin(fp_phone, fp_new_pin)
                                     st.success("PIN Reset Successful! Please Login.")
                                 else:
                                     st.error("New PIN must be 4 digits.")
                             else:
                                 st.error("Incorrect Answer.")
                    else:
                        st.warning("User not found.")

        elif selected == "Register":
            with st.form("register_form"):
                st.markdown("### <i class='fa-solid fa-user-plus'></i> Create New Account", unsafe_allow_html=True)
                new_name = st.text_input("Full Name")
                new_phone = st.text_input("Phone Number")
                new_pin = st.text_input("Create PIN (4 digits)", type="password", max_chars=4)
                
                st.markdown("---")
                st.markdown("**Security Question (for Account Recovery)**")
                sec_q = st.selectbox("Select a Question", [
                    "What is your mother's maiden name?",
                    "What was the name of your first pet?",
                    "Which city were you born in?",
                    "What is your favorite food?"
                ])
                sec_a = st.text_input("Answer")
                
                reg_submitted = st.form_submit_button("Register")
                if reg_submitted:
                    if not validate_phone(new_phone):
                        st.error("Invalid Phone Number (Use 10-15 digits only)")
                    elif new_name and new_phone and len(new_pin) == 4 and new_pin.isdigit() and sec_a:
                        success, msg = user_manager.register(new_phone, new_name, new_pin, sec_q, sec_a)
                        if success:
                            st.success(f"Success! {msg}. Please Login.")
                        else:
                            st.error(f"Error: {msg}")
                    else:
                        st.warning("Please fill all fields correctly.")

else:
    if getattr(current_user, 'role', 'user') == 'admin':
        # --- ADMIN DASHBOARD ---
        with st.sidebar:
            st.title("Admin Panel")
            st.markdown(f"User: {current_user.name}")
            if st.button("Logout", key="admin_logout"):
                logout_user()
        
        st.markdown("## 🛡️ Administrative Overview")
        
        # Calculate Metrics
        total_users = len(user_manager.users)
        # Exclude admin from liquidity if you want, but admin might have money too.
        total_liquidity = sum(u.balance for u in user_manager.users.values()) 
        
        # Calculate Fees
        all_tx = transaction_manager.transactions
        total_fees = sum(t.amount for t in all_tx if t.receiver_phone == "SYSTEM_REVENUE")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Users", total_users)
        col2.metric("System Liquidity", f"${total_liquidity:,.2f}")
        col3.metric("Revenue (Fees)", f"${total_fees:,.2f}")
        
        tab1, tab2 = st.tabs(["User Directory", "Transaction Logs"])
        
        with tab1:
            st.markdown("### Registered Users")
            user_data = [{"Name": u.name, "Phone": u.phone, "Balance": u.balance, "Role": u.role} for u in user_manager.users.values()]
            st.dataframe(user_data, use_container_width=True)
            
        with tab2:
            st.markdown("### Transaction History")
            tx_data = [t.to_dict() for t in all_tx]
            tx_data.sort(key=lambda x: x['timestamp'], reverse=True)
            st.dataframe(tx_data, use_container_width=True)
        
        st.stop()

    # --- Dashboard View ---
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align: center; padding: 20px;">
            <i class="fa-solid fa-circle-user fa-5x" style="color: #4CAF50;"></i>
            <h3>{current_user.name}</h3>
            <p style="color: gray;"><i class="fa-solid fa-phone"></i> {current_user.phone}</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("Logout"):
            logout_user()
    
    # Balance Section
    st.markdown(f"### <i class='fa-solid fa-hand-spock'></i> Hello, {current_user.name.split()[0]}", unsafe_allow_html=True)
    
    col_bal, col_act = st.columns([1, 2])
    
    with col_bal:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Current Balance</div>
            <div class="metric-value"><i class="fa-solid fa-wallet"></i> ${current_user.balance:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_act:
        st.info("Select an action from the menu below to perform a transaction.")

    st.markdown("---")

    # Operations using Option Menu
    selected_action = option_menu(
        menu_title=None,
        options=["Send Money", "Pay Bills", "Load Money", "Withdraw", "Inbox", "History", "Settings"],
        icons=["send", "receipt", "credit-card", "arrow-up-circle", "envelope", "clock-history", "gear"],
        default_index=0,
        orientation="horizontal",
    )

    # --- RESET Review State on Tab Change ---
    if 'last_selected_action' not in st.session_state:
        st.session_state.last_selected_action = selected_action
        st.session_state.review_mode = False
        st.session_state.review_data = {}

    if st.session_state.last_selected_action != selected_action:
        st.session_state.review_mode = False
        st.session_state.review_data = {}
        st.session_state.last_selected_action = selected_action

    if selected_action == "Send Money":
        if not st.session_state.review_mode:
            st.subheader("Send Money to Another User")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                receiver_phone = st.text_input("Receiver's Phone Number", key="send_ph")
            with col_s2:
                send_amount = st.number_input("Amount to Send ($)", min_value=1.0, step=5.0, key="send_amt")
            
            send_desc = st.text_input("Description (e.g. Lunch, Rent)", key="send_desc")

            if st.button("Proceed to Verification", type="primary"):
                # Input Validation
                if not receiver_phone:
                    st.error("Please enter a receiver phone number.")
                elif receiver_phone == current_user.phone:
                    st.error("You cannot send money to yourself.")
                elif send_amount <= 0:
                     st.error("Amount must be greater than 0.")
                else:
                    rx_user = user_manager.get_user(receiver_phone)
                    if not rx_user:
                        st.error("Receiver not found in the system.")
                    else:
                        st.session_state.review_mode = True
                        st.session_state.review_data = {
                            "type": "TRANSFER",
                            "receiver_phone": receiver_phone,
                            "receiver_name": rx_user.name,
                            "amount": send_amount,
                            "desc": send_desc
                        }
                        st.rerun()
        else:
            # Verification View
             data = st.session_state.review_data
             st.subheader("Verify Transaction Details")
             st.info("Please review the details below carefully before confirming.")
             
             # Fee Calculation
             fee = data['amount'] * 0.01
             total_deduction = data['amount'] + fee

             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Recipient</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: #333;">{data['receiver_name']}</span> <br/>
                        <span style="color: gray; font-family: monospace;">{data['receiver_phone']}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Amount</span><br/>
                        <span class="conf-amount" style="color: #4CAF50;">${data['amount']:,.2f}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Fee (1%)</span><br/>
                        <span style="font-size: 1.1em; color: #777;">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total Deduction</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: #d9534f;">${total_deduction:,.2f}</span>
                    </div>
                    <div>
                        <span class="conf-label">Reference</span><br/>
                        <span style="font-style: italic;">{data['desc'] if data['desc'] else 'No description'}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)
                 
                 st.write("") 
                 st.write("") 
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button("Cancel", use_container_width=True):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm Transfer", type="primary", use_container_width=True):
                         success, msg = transaction_manager.transfer(current_user.phone, data['receiver_phone'], data['amount'], data['desc'])
                         if success:
                             st.success(f"Success! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(2)
                             st.rerun()
                         else:
                             st.error(f"Error: {msg}")

    elif selected_action == "Pay Bills":
        if not st.session_state.review_mode:
            st.subheader("Pay Bills & Utilities")
            
            bill_type = st.selectbox("Select Biller Category", ["Airtime & Data", "Electricity (Prepaid)", "Water Utility", "Internet Subscription"])
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if bill_type == "Airtime & Data":
                    biller_id = st.text_input("Phone Number", value=current_user.phone)
                    biller_name = "Telecel/Lonestar"
                elif bill_type == "Electricity (Prepaid)":
                    biller_id = st.text_input("Meter Number")
                    biller_name = "LEC Power"
                else:
                    biller_id = st.text_input("Account/customer ID")
                    biller_name = "Utility Provider"
                    
            with col_b2:
                bill_amount = st.number_input("Amount ($)", min_value=1.0, step=5.0)
                
            if st.button("Proceed to Pay"):
                if not biller_id:
                    st.error("Please enter the ID number.")
                elif bill_amount <= 0:
                     st.error("Invalid amount")
                else:
                    st.session_state.review_mode = True
                    st.session_state.review_data = {
                        "type": "BILL_PAYMENT",
                        "biller_name": biller_name,
                        "biller_id": biller_id,
                        "amount": bill_amount,
                        "desc": bill_type
                    }
                    st.rerun()
        else:
             data = st.session_state.review_data
             st.subheader("Confirm Bill Payment")
             
             fee = 0.50
             total = data['amount'] + fee
             
             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                         <span class="conf-label">Service</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: #333;">{data['biller_name']}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Account/ID</span><br/>
                        <span style="font-family: monospace; font-size: 1.1em;">{data['biller_id']}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Amount</span><br/>
                        <span class="conf-amount">${data['amount']:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px;">
                        <span class="conf-label">Service Fee</span><br/>
                        <span style="color: #777;">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total to Pay</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: #d9534f;">${total:,.2f}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)
                 
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button("Cancel", use_container_width=True):
                         st.session_state.review_mode = False
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm Payment", type="primary", use_container_width=True):
                         success, msg = transaction_manager.pay_bill(current_user.phone, data['amount'], data['biller_name'], data['biller_id'], data['desc'])
                         if success:
                             st.success(f"Success! {msg}")
                             st.session_state.review_mode = False
                             time.sleep(2)
                             st.rerun()
                         else:
                             st.error(f"Error: {msg}")

    elif selected_action == "Inbox":
        st.subheader("Notifications & Alerts")
        all_tx = transaction_manager.get_history(current_user.phone)
        notifications = []
        
        # Derive alerts
        for t in all_tx:
            if t.receiver_phone == current_user.phone and t.type == "TRANSFER":
                notifications.append({
                    "time": t.timestamp,
                    "title": "Money Received",
                    "msg": f"You received ${t.amount:,.2f} from {t.sender_phone}",
                    "icon": "fa-arrow-down",
                    "color": "#5cb85c"
                })
            elif t.type == "BILL_PAYMENT" and t.sender_phone == current_user.phone:
                notifications.append({
                    "time": t.timestamp,
                    "title": "Bill Paid",
                    "msg": f"Payment of ${t.amount:,.2f} for {t.description} successful.",
                    "icon": "fa-receipt",
                    "color": "gray"
                })
            elif t.type == "DEPOSIT" and t.sender_phone == "SYSTEM": 
                 if t.receiver_phone == current_user.phone: # It's a credit
                     notifications.append({
                        "time": t.timestamp,
                        "title": "Deposit Successful",
                        "msg": f"Your account was credited with ${t.amount:,.2f}.",
                        "icon": "fa-wallet",
                        "color": "#4CAF50"
                    })

        if not notifications:
            st.info("No notifications.")
        else:
            notifications.sort(key=lambda x: x['time'], reverse=True)
            for n in notifications:
                st.markdown(f"""
                <div style="padding: 15px; border-bottom: 1px solid #eee; display: flex; align-items: start;">
                    <div style="margin-right: 15px; color: {n['color']};"><i class="fa-solid {n['icon']}"></i></div>
                    <div>
                        <div style="font-weight: bold; font-size: 0.95em;">{n['title']}</div>
                        <div style="color: #555; font-size: 0.9em;">{n['msg']}</div>
                        <div style="color: #999; font-size: 0.75em; margin-top: 4px;">{n['time'].replace('T', ' ')[:16]}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)


    elif selected_action == "Load Money":
        if not st.session_state.review_mode:
            st.subheader("Load Wallet from Bank")
            st.info("Link your Debit/Credit card to fund your wallet.")
            
            # Mock Card Input
            col_c1, col_c2 = st.columns([2, 1])
            with col_c1:
                st.text_input("Card Number", placeholder="0000 0000 0000 0000")
            with col_c2:
                st.text_input("CVV", type="password", max_chars=3)
            
            col_ca1, col_ca2 = st.columns(2)
            with col_ca1:
                st.text_input("Expiry Date", placeholder="MM/YY")
            with col_ca2:
                dep_amount = st.number_input("Amount to Load ($)", min_value=1.0, step=100.0, key="dep_u")
                
            dep_desc = "Bank Transfer"

            if st.button("Proceed to Verification", type="primary"):
                if dep_amount <= 0:
                    st.error("Amount must be greater than 0.")
                else:
                    st.session_state.review_mode = True
                    st.session_state.review_data = {
                        "type": "DEPOSIT",
                        "amount": dep_amount,
                        "desc": dep_desc
                    }
                    st.rerun()
        else:
             data = st.session_state.review_data
             st.subheader("Confirm Details")
             
             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Source</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: #333;">Linked Bank Card</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Amount to Load</span><br/>
                        <span class="conf-amount">${data['amount']:,.2f}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)
                 
                 st.write("")
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button("Cancel", use_container_width=True):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm & Load", type="primary", use_container_width=True):
                         success, msg = transaction_manager.deposit(current_user.phone, data['amount'], data['desc'])
                         if success:
                             st.success(f"Success! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(1)
                             st.rerun()
                         else:
                             st.error(f"Error: {msg}")
    
    elif selected_action == "Withdraw":
        if not st.session_state.review_mode:
            st.subheader("Withdraw Funds")
            with_amount = st.number_input("Amount to Withdraw ($)", min_value=1.0, step=10.0, key="with_u")
            with_desc = st.text_input("Purpose/Description (Optional)", key="with_desc")
            
            if st.button("Proceed to Verification", type="primary"):
                 if with_amount <= 0:
                    st.error("Amount must be greater than 0.")
                 elif with_amount > current_user.balance:
                    st.error("Insufficient balance.")
                 else:
                    st.session_state.review_mode = True
                    st.session_state.review_data = {
                        "type": "WITHDRAWAL",
                        "amount": with_amount,
                        "desc": with_desc or "Withdrawal"
                    }
                    st.rerun()
        else:
             data = st.session_state.review_data
             st.subheader("Verify Withdrawal Details")
             st.info("Please confirm the withdrawal details below.")
             
             # Calculate Fee
             fee = data['amount'] * 0.01
             total_deduction = data['amount'] + fee
             
             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Transaction Type</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: #d9534f;">WITHDRAWAL</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Amount</span><br/>
                        <span class="conf-amount">${data['amount']:,.2f}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Fee (1%)</span><br/>
                        <span style="font-size: 1.1em; color: #777;">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total Deduction</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: #d9534f;">${total_deduction:,.2f}</span>
                    </div>
                    <div>
                        <span class="conf-label">Reference</span><br/>
                        <span style="font-style: italic;">{data['desc']}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)
                 
                 st.write("")
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button("Cancel", use_container_width=True):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm Withdrawal", type="primary", use_container_width=True):
                         success, msg = transaction_manager.withdraw(current_user.phone, data['amount'], data['desc'])
                         if success:
                             st.success(f"Success! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(1)
                             st.rerun()
                         else:
                             st.error(f"Error: {msg}")

    elif selected_action == "Settings":
        st.subheader("Profile Settings")
        
        with st.form("settings_form"):
            st.markdown("### Update Profile")
            new_name = st.text_input("Full Name", value=current_user.name)
            new_pin = st.text_input("New PIN (Leave blank to keep current)", type="password", max_chars=4)
            
            st.markdown("---")
            st.markdown("**Update Security Question**")
            current_q_index = 0
            options = [
                "What is your mother's maiden name?",
                "What was the name of your first pet?",
                "Which city were you born in?",
                "What is your favorite food?"
            ]
            
            # Try to find current question index if it exists
            if current_user.sec_q in options:
                current_q_index = options.index(current_user.sec_q)
                
            new_sec_q = st.selectbox("Select a Question", options, index=current_q_index)
            new_sec_a = st.text_input("New Answer (Leave blank to keep current)")
            
            if st.form_submit_button("Update Profile"):
                valid = True
                if new_pin and (len(new_pin) != 4 or not new_pin.isdigit()):
                    st.error("PIN must be 4 digits")
                    valid = False
                
                if valid:
                    # Pass None if empty so it doesn't change
                    pin_arg = new_pin if new_pin else None
                    qs_arg = new_sec_q
                    ans_arg = new_sec_a if new_sec_a else None
                    
                    success, msg = user_manager.update_user(current_user.phone, name=new_name, pin=pin_arg, sec_q=qs_arg, sec_a=ans_arg)
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
    elif selected_action == "History":
        st.subheader("Recent Transactions")
        history = transaction_manager.get_history(current_user.phone)
        
        if not history:
            st.info("No transactions yet.")
        else:
            # Sort by timestamp descending
            history.sort(key=lambda x: x.timestamp, reverse=True)
            
            for t in history:
                # Determine icon/color
                if t.type == "TRANSFER":
                    if t.sender_phone == current_user.phone:
                         icon = "fa-solid fa-arrow-turn-up"
                         color = "#d9534f" # Red
                         badge = "DEBIT"
                         desc_text = f"To: {t.receiver_phone}"
                    else:
                         icon = "fa-solid fa-arrow-turn-down"
                         color = "#5cb85c" # Green
                         badge = "CREDIT"
                         desc_text = f"From: {t.sender_phone}"
                elif t.type == "DEPOSIT":
                    icon = "fa-solid fa-circle-plus"
                    color = "#5cb85c"
                    badge = "CREDIT"
                    desc_text = "System Deposit"
                elif t.type == "WITHDRAWAL":
                    icon = "fa-solid fa-circle-minus"
                    color = "#d9534f"
                    badge = "DEBIT"
                    desc_text = "System Withdrawal"
                elif t.type == "BILL_PAYMENT":
                    icon = "fa-solid fa-file-invoice-dollar"
                    color = "#d9534f"
                    badge = "DEBIT"
                    desc_text = "Bill Payment"
                else:
                    icon = "fa-solid fa-list"
                    color = "gray"
                    badge = "INFO"
                    desc_text = "Transaction"

                # Check for custom description
                if hasattr(t, 'description') and t.description:
                    detail_text = t.description
                else:
                    detail_text = desc_text
                
                # Get Sender/Receiver Names
                sender_name = "System"
                receiver_name = "System"
                
                if t.sender_phone != "SYSTEM":
                     s_user = user_manager.get_user(t.sender_phone)
                     sender_name = s_user.name if s_user else "Unknown"

                if t.receiver_phone != "SYSTEM":
                     r_user = user_manager.get_user(t.receiver_phone)
                     receiver_name = r_user.name if r_user else "Unknown"
                
                # Receipt Content
                receipt_text = f"""--- TRANSACTION RECEIPT ---
Date: {t.timestamp}
ID: {t.id}
Type: {t.type}
Amount: ${t.amount:,.2f}
Detail: {detail_text}
Sender: {sender_name} ({t.sender_phone})
Receiver: {receiver_name} ({t.receiver_phone})
Status: Successful
---------------------------"""

                # Custom HTML Transaction Card inside Expander
                with st.expander(f"{t.timestamp[:10]} - {detail_text} - ${t.amount:,.2f}"):
                    st.markdown(f"""
                    <div style="background-color: white; padding: 15px; border-radius: 8px; border-left: 5px solid {color}; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="display: flex; align-items: center;">
                                <div style="background-color: {color}20; padding: 10px; border-radius: 50%; margin-right: 15px;">
                                    <i class="{icon}" style="color: {color}; font-size: 1.2em;"></i>
                                </div>
                                <div>
                                    <div style="font-weight: bold; font-size: 1.1em; color: #333;">{detail_text}</div>
                                    <div style="font-size: 0.85em; color: gray;">
                                        <i class="fa-regular fa-clock"></i> {t.timestamp.replace('T', ' ')[:16]} 
                                    </div>
                                </div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-weight: bold; color: {color}; font-size: 1.2em;">${t.amount:,.2f}</div>
                                 <div style="font-size: 0.7em; background-color: {color}; color: white; padding: 2px 8px; border-radius: 12px; display: inline-block; font-weight: 600;">{badge}</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown("#### Transaction Details")
                    col_d1, col_d2 = st.columns(2)
                    
                    with col_d1:
                        st.markdown(f"**Transaction ID:** `{t.id}`")
                        st.markdown(f"**Date:** {t.timestamp}")
                        st.markdown(f"**Type:** {t.type}")

                    with col_d2:
                        st.markdown(f"**Sender:** {sender_name}")
                        st.caption(f"Phone: {t.sender_phone}")
                        st.markdown(f"**Recipient:** {receiver_name}")
                        st.caption(f"Phone: {t.receiver_phone}")
                    
                    st.download_button(
                        label="Download Receipt", 
                        data=receipt_text, 
                        file_name=f"receipt_{t.id}.txt", 
                        mime="text/plain",
                        key=f"dl_{t.id}"
                    )

