import streamlit as st
from streamlit_option_menu import option_menu
from users import UserManager
from transactions import TransactionManager
from i18n import get_text
from styles import get_custom_css
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

# Apply Custom CSS
st.markdown(get_custom_css(), unsafe_allow_html=True)

# --- Language Setup ---
if 'language' not in st.session_state:
    st.session_state.language = "en"

def TR(key):
    return get_text(st.session_state.language, key)

# Sidebar Language Selector
with st.sidebar:
    lang_choice = st.selectbox(
        "🌐 Language / Langue / Idioma / Lugha", 
        ["English", "Français", "Español", "Swahili"], 
        index=["en", "fr", "es", "sw"].index(st.session_state.language)
    )
    if lang_choice == "English":
        st.session_state.language = "en"
    elif lang_choice == "Français":
        st.session_state.language = "fr"
    elif lang_choice == "Español":
        st.session_state.language = "es"
    elif lang_choice == "Swahili":
        st.session_state.language = "sw"

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


def logout_user():
    st.session_state.current_user_phone = None
    if 'otp_verified' in st.session_state:
        del st.session_state.otp_verified
    st.rerun()

# --- Application Layout ---

st.markdown(f"""
<style>
@media (max-width: 768px) {{
    .app-title {{
        font-size: 1.8rem !important;
    }}
}}
</style>
<h1 class="app-title" style="text-align: center; color: #4CAF50;"><i class="fa-solid fa-money-bill-transfer"></i> {TR('app_title')}</h1>
""", unsafe_allow_html=True)

if not current_user:
    # --- Auth View ---
    st.markdown(f"<h3 style='text-align: center; margin-bottom: 2rem;'>{TR('welcome')}</h3>", unsafe_allow_html=True)
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        selected = option_menu(
            menu_title=None,
            options=[TR("login"), TR("register")],
            icons=["box-arrow-in-right", "person-plus"],
            menu_icon="cast",
            default_index=0,
            orientation="horizontal",
            styles={
                "container": {"background-color": "transparent"},
                "nav-link": {"font-size": "14px"},
                "nav-link-selected": {"background-color": "#00C853"},
            }
        )
        
        if selected == TR("login"):
            # State Management for 2FA Login Flow
            if 'login_stage' not in st.session_state:
                st.session_state.login_stage = 'credentials' # credentials -> otp
            
            if st.session_state.login_stage == 'credentials':
                with st.form("login_form"):
                    st.markdown(f"### {TR('login')}")
                    phone = st.text_input(TR("phone"), placeholder="077xxxxxxx")
                    pin = st.text_input(TR("pin"), type="password", placeholder="****")
                    st.write("")
                    submitted = st.form_submit_button(TR("login_btn"), type="primary")
                    
                    if submitted:
                        if phone and pin:
                            # Verify Credentials First
                            user = user_manager.login(phone, pin)
                            if user:
                                # Move to OTP Stage
                                st.session_state.login_stage = 'otp'
                                st.session_state.temp_phone = phone
                                st.session_state.temp_pin = pin # Keep temporarily
                                st.rerun()
                            else:
                                st.error("Invalid Phone Number or PIN")
                        else:
                            st.warning("Please enter both Phone and PIN")
            
            elif st.session_state.login_stage == 'otp':
                st.markdown(f"### <i class='fa-solid fa-shield-halved'></i> 2FA Verification", unsafe_allow_html=True)
                st.caption(f"Code sent to {st.session_state.temp_phone}")
                
                # Auto-send OTP logic (only once)
                if 'otp_sent_flag' not in st.session_state:
                    code = user_manager.generate_otp(st.session_state.temp_phone)
                    st.session_state.generated_code = code # Store for display
                    st.toast(f"🔐 Security Code: {code}", icon="📩")
                    st.session_state.otp_sent_flag = True
                
                # Display Code for easier testing
                if 'generated_code' in st.session_state:
                    st.info(f"Simulation: Your Security Code is **{st.session_state.generated_code}**")
                
                otp_code = st.text_input("Security Code", key="otp_input_field")
                
                col_ver, col_back = st.columns(2)
                with col_ver:
                    if st.button("Verify"):
                        if user_manager.verify_otp(st.session_state.temp_phone, otp_code):
                            # Success: Log in
                            st.session_state.current_user_phone = st.session_state.temp_phone
                            # Cleanup
                            del st.session_state.login_stage
                            del st.session_state.temp_phone
                            del st.session_state.temp_pin
                            if 'otp_sent_flag' in st.session_state:
                                del st.session_state.otp_sent_flag
                            if 'generated_code' in st.session_state:
                                del st.session_state.generated_code
                            st.rerun()
                        else:
                            st.error("Invalid Code")
                with col_back:
                    if st.button("Back"):
                        st.session_state.login_stage = 'credentials'
                        if 'otp_sent_flag' in st.session_state:
                            del st.session_state.otp_sent_flag
                        st.rerun()
            
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

        elif selected == TR("register"):
            with st.form("register_form"):
                st.markdown(f"### <i class='fa-solid fa-user-plus'></i> {TR('register')}", unsafe_allow_html=True)
                new_name = st.text_input("Full Name")
                new_phone = st.text_input(TR("phone"))
                new_pin = st.text_input("Create PIN (4 digits)", type="password", max_chars=4)
                
                st.markdown("---")
                st.markdown("**Security Question (for Account Recovery)**")
                currency = st.selectbox("Preferred Currency", ["USD", "EUR", "KES", "GBP"], index=0)
                sec_q = st.selectbox("Select a Question", [
                    "What is your mother's maiden name?",
                    "What was the name of your first pet?",
                    "Which city were you born in?",
                    "What is your favorite food?"
                ])
                sec_a = st.text_input("Answer")
                
                reg_submitted = st.form_submit_button(TR("register"))
                if reg_submitted:
                    if not validate_phone(new_phone):
                        st.error("Invalid Phone Number (Use 10-15 digits only)")
                    elif new_name and new_phone and len(new_pin) == 4 and new_pin.isdigit() and sec_a:
                        success, msg = user_manager.register(new_phone, new_name, new_pin, sec_q, sec_a, currency)
                        if success:
                            st.success(f"Success! {msg}. Please Login.")
                        else:
                            st.error(f"Error: {msg}")
                    else:
                        st.warning("Please fill all fields correctly.")

else:
    # DEBUG: Check Role
    # st.write(f"Debug: Role is {getattr(current_user, 'role', 'user')}")
    
    if getattr(current_user, 'role', 'user') == 'admin':
        # --- ADMIN DASHBOARD ---
        st.sidebar.title("🛡️ Admin Panel")
        st.sidebar.write(f"**Admin:** {current_user.name}")
            
        # Impersonation Exit
        if st.session_state.get('impersonating', False):
             st.sidebar.warning("⚠️ Impersonation Active")
             if st.sidebar.button("Exit Impersonation", type="primary", width="stretch"):
                 del st.session_state.user
                 del st.session_state.impersonating
                 st.rerun()

        if st.sidebar.button(TR("logout"), key="admin_logout", width="stretch"):
            logout_user()
        
        st.markdown(f"## <i class='fa-solid fa-layer-group'></i> System Administration")
        
        # Admin Metrics
        col1, col2, col3, col4 = st.columns(4)
        total_users = len(user_manager.users)
        total_balance = sum(u.balance for u in user_manager.users.values())
        tx_count = len(transaction_manager.transactions)
        flagged_count = len([t for t in transaction_manager.transactions if t.flagged])
        
        col1.metric("Users", total_users)
        col2.metric("Total Float", f"${total_balance:,.2f}")
        col3.metric("Transactions", tx_count)
        col4.metric("Risk Alerts", flagged_count, delta_color="inverse")

        # Admin Navigation
        selected_adm = option_menu(
            menu_title=None,
            options=["Users", "Transactions", "Bills & Revenue", "Security", "Analytics", "System", "Support"],
            icons=["people", "cash-coin", "receipt", "shield-lock", "graph-up", "gear", "headset"],
            default_index=0,
            orientation="horizontal",
            styles={"nav-link": {"font-size": "14px"}}
        )

        # ---------------- USERS TAB ----------------
        if selected_adm == "Users":
            st.subheader("👥 User Management")
            
            # Search & Filter
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                search_q = st.text_input("Search Users", placeholder="Phone, Name, or ID Number...")
            with col_s2:
                filter_status = st.selectbox("Status", ["All", "Active", "Suspended", "Deleted"])
            
            # Filter Logic
            users_list = []
            for u in user_manager.users.values():
                # Filter by Status
                if filter_status != "All" and u.status.lower() != filter_status.lower():
                    continue
                    
                # Search
                q = search_q.lower()
                if not q or q in u.phone or (u.name and q in u.name.lower()) or (u.id_number and q in u.id_number):
                    users_list.append(u)
            
            st.dataframe([u.to_dict() for u in users_list], width="stretch")
            
            # Action Panel
            st.markdown("### 🛠️ Account Actions")
            if users_list:
                selected_user_phone = st.selectbox("Select Target User", [u.phone for u in users_list], format_func=lambda x: f"{x} - {user_manager.users[x].name}")
                target_u = user_manager.users[selected_user_phone]
                
                with st.expander(f"Manage: {target_u.name} ({target_u.phone})", expanded=True):
                    col_act1, col_act2, col_act3 = st.columns(3)
                    
                    with col_act1:
                        st.markdown("**KYC & Status**")
                        if st.button("Verify KYC", disabled=target_u.is_verified, width="stretch", key="btn_kyc"):
                            user_manager.submit_kyc(target_u.phone, "manual_admin", "VERIFIED")
                            st.success("User Verified")
                            time.sleep(1)
                            st.rerun()
                            
                        if target_u.status == "active":
                             if st.button("Suspend Account", type="primary", width="stretch", key="btn_susp"):
                                 user_manager.suspend_user(target_u.phone)
                                 st.warning("User Suspended")
                                 time.sleep(1)
                                 st.rerun()
                        else:
                             if st.button("Reactivate Account", type="primary", width="stretch", key="btn_react"):
                                 user_manager.reactivate_user(target_u.phone)
                                 st.success("User Reactivated")
                                 time.sleep(1)
                                 st.rerun()

                    with col_act2:
                        st.markdown("**Security**")
                        if st.button("Reset PIN", width="stretch", key="btn_pin"):
                             success, msg = user_manager.admin_reset_pin(target_u.phone)
                             st.info(msg)
                        
                        risk_tier = st.selectbox("Risk Tier", ["low", "standard", "high"], index=["low", "standard", "high"].index(target_u.risk_tier))
                        if risk_tier != target_u.risk_tier:
                            if st.button("Update Risk Tier", width="stretch"):
                                user_manager.update_user(target_u.phone, risk_tier=risk_tier)
                                st.success(f"Risk tier updated to {risk_tier}")
                                time.sleep(1)
                                st.rerun()

                    with col_act3:
                         st.markdown("**Support**")
                         if st.button("Impersonate User", width="stretch", key="btn_imp"):
                             st.session_state.user = target_u
                             st.session_state.impersonating = True
                             st.rerun()
                             
                         if st.button("HARD DELETE", type="primary", width="stretch"):
                             st.error("Feature valid but dangerous. Simulated delete.")

        # ---------------- TRANSACTIONS TAB ----------------
        elif selected_adm == "Transactions":
            st.subheader("💳 Transaction Oversight")
            
            # Live Feed
            all_tx = transaction_manager.transactions
            tx_data = [t.to_dict() for t in all_tx]
            tx_data.sort(key=lambda x: x['timestamp'], reverse=True)
            st.dataframe(tx_data, width="stretch")
            
            col_t1, col_t2 = st.columns(2)
            
            with col_t1:
                st.markdown("### 🔙 Reversal Console")
                rev_id = st.text_input("Enter Transaction ID to Reverse")
                if st.button("Reverse Transaction", type="primary", key="btn_rev"):
                    success, msg = transaction_manager.reverse_transaction(rev_id)
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
                        
            with col_t2:
                st.markdown("### 💵 Manual Adjustment")
                adj_phone = st.text_input("Target User Phone")
                adj_amount = st.number_input("Amount", min_value=0.0)
                adj_type = st.radio("Type", ["Credit (+)", "Debit (-)"])
                adj_reason = st.text_input("Reason Code / Note")
                
                if st.button("Execute Adjustment", key="btn_adj"):
                    is_credit = adj_type == "Credit (+)"
                    success, msg = transaction_manager.admin_adjust_balance(adj_phone, adj_amount, f"ADMIN_ADJ: {adj_reason}", is_credit)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

        # ---------------- BILLS & REVENUE TAB ----------------
        elif selected_adm == "Bills & Revenue":
            st.subheader("🧾 Utilities & Fees")
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                 st.markdown("### Revenue Stream")
                 revenue_tx = [t for t in transaction_manager.transactions if t.receiver_phone == "SYSTEM_REVENUE"]
                 total_rev = sum(t.amount for t in revenue_tx)
                 st.metric("Total Fee Revenue", f"${total_rev:,.2f}")
                 st.bar_chart([t.amount for t in revenue_tx])
                 
            with col_b2:
                 st.markdown("### Utility Providers")
                 # Mock Config
                 providers = [
                     {"name": "KPLC Power", "cat": "Electricity", "fee": "1.5%"},
                     {"name": "Nairobi Water", "cat": "Water", "fee": "0.0%"},
                     {"name": "Zuku Fiber", "cat": "Internet", "fee": "2.0%"}
                 ]
                 st.table(providers)
                 with st.expander("Add Provider"):
                     st.text_input("Provider Name")
                     st.selectbox("Category", ["Electricity", "Water", "Internet", "Gov"])
                     st.text_input("Fee %")
                     st.button("Save Provider (Mock)")

        # ---------------- SECURITY TAB ----------------
        elif selected_adm == "Security":
            st.subheader("🛡️ Security Center")
            
            flagged = [t for t in transaction_manager.transactions if t.flagged]
            if flagged:
                st.error(f"{len(flagged)} Suspicious Transactions Detected")
                for t in flagged:
                    st.warning(f"{t.id} | {t.sender_phone} -> {t.receiver_phone} | ${t.amount} | Reason: {t.flag_reason}")
            else:
                st.success("No active security alerts.")
                
            st.markdown("### Fraud Rules Configuration")
            st.checkbox("Block transfers > $500 to new recipients", value=True)
            st.checkbox("Auto-freeze account after 3 failed PIN attempts", value=True)
            st.checkbox("IP Geofencing (Allow only specific countries)", value=False)
            st.button("Update Security Rules")

        # ---------------- ANALYTICS TAB ----------------
        elif selected_adm == "Analytics":
            st.subheader("📊 Reports & Analytics")
            st.info("Export data for external analysis.")
            
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                st.markdown("**User Data**")
                st.download_button("Download Users CSV", data="mock_csv_data", file_name="users.csv")
            with col_exp2:
                st.markdown("**Transaction Logs**")
                st.download_button("Download Transactions CSV", data="mock_csv_data", file_name="transactions.csv")
                
            st.markdown("### Growth Metrics")
            st.line_chart([10, 15, 20, 25, 40, 55, 60, 80]) # Mock growth

        # ---------------- SYSTEM TAB ----------------
        elif selected_adm == "System":
            st.subheader("⚙️ System Configuration")
            st.selectbox("System Status", ["Operational", "Maintenance Mode", "ReadOnly"])
            
            st.markdown("**Fee Configuration**")
            col_sys1, col_sys2 = st.columns(2)
            with col_sys1:
                st.number_input("P2P Transfer Fee (%)", value=1.0)
                st.number_input("Withdrawal Fee (%)", value=2.0)
            with col_sys2:
                 st.number_input("Bill Payment Fee (Fixed)", value=0.5)
                 st.number_input("Forex Margin (%)", value=2.5)
            
            st.button("Save System Config")

        # ---------------- SUPPORT TAB ----------------
        elif selected_adm == "Support":
            st.subheader("🧑‍💼 Agent Support Console")
            st.info("Ticket System Integration (Mock)")
            
            tickets = [
                {"id": 101, "user": "0987654321", "issue": "Money deducted but not received", "status": "Open"},
                {"id": 102, "user": "0777123456", "issue": "Forgot PIN", "status": "Resolved"}
            ]
            st.table(tickets)
            
            with st.expander("Resolve Ticket #101"):
                st.text_area("Admin Note")
                st.selectbox("New Status", ["Open", "Pending", "Resolved"])
                st.button("Update Ticket")

        st.stop()

    # --- Dashboard View ---
    
    # Sidebar
    with st.sidebar:
        # Impersonation Exit for Admin
        if st.session_state.get('impersonating', False):
            st.error("⚠️ IMPERSONATING USER")
            if st.button("EXIT IMPERSONATION", type="primary", width="stretch"):
                # We need to restore the admin session. 
                # Ideally we stored the admin user in session state too, but simply clearing 'user' forces login.
                # Retaining the login would require storing 'admin_user' separately.
                # For this prototype, forcing re-login is safer/easier.
                del st.session_state.user
                del st.session_state.impersonating
                st.rerun()
            st.markdown("---")

        st.markdown(f"""
        <div style="text-align: center; padding: 20px;">
            <i class="fa-solid fa-circle-user fa-5x" style="color: #4CAF50;"></i>
            <h3>{current_user.name}</h3>
            <p style="color: gray;"><i class="fa-solid fa-phone"></i> {current_user.phone}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # QR Code Display
        try:
            import qrcode
            from io import BytesIO
            import base64
            
            # Create QR Data
            qr_data = f"MMS:{current_user.phone}"
            qr = qrcode.QRCode(version=1, box_size=5, border=2)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to Displayable format
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 20px; padding: 10px; background: white; border-radius: 10px;">
                <p style='font-size: 0.8em; color: gray;'>Scan to Request/Pay</p>
                <img src="data:image/png;base64,{img_str}" width="150" />
            </div>
            """, unsafe_allow_html=True)
        except ImportError:
            st.warning("Install 'qrcode' to see QR.")
        
        if st.button(TR("logout")):
            logout_user()
    
    # Balance Section
    st.markdown(f"### <i class='fa-solid fa-hand-spock'></i> {TR('hello')}, {current_user.name.split()[0]}", unsafe_allow_html=True)
    
    if not current_user.is_verified:
         st.error(f"⚠️ **{TR('kyc_needed')}** limit: transactions blocked.", icon="🚫")

    # Brand New Opay-Style Wallet Card
    st.markdown(f"""
    <div class="wallet-card">
        <div style="display: flex; justify-content: space-between; align-items: start;">
            <div>
                <div class="balance-label">{TR('balance')} <i class="fa-regular fa-eye-slash"></i></div>
                <div class="balance-value">{current_user.currency} {current_user.balance:,.2f}</div>
                <div class="wallet-details">
                    <span style="background: rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 10px;">Active</span>
                </div>
            </div>
            <div style="text-align: right; color: rgba(255,255,255,0.8);">
                <i class="fa-solid fa-signal"></i><br/>
                <small>{current_user.phone}</small>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Quick Actions Grid (To mimic app home screen)
    # Using columns for buttons to simulate the "Grid"
    
    st.markdown("##### Quick Actions")

    # Operations using Option Menu (Styled as Tab Bar)
    selected_action = option_menu(
        menu_title=None,
        options=[TR("send"), TR("request"), TR("pay_bills"), TR("load"), TR("withdraw"), TR("inbox"), TR("history"), TR("settings"), TR("verify_id")],
        icons=["send", "arrow-left-circle", "receipt", "credit-card", "arrow-up-circle", "envelope", "clock-history", "gear", "card-heading"],
        default_index=0,
        orientation="horizontal",
        styles={
            "container": {"padding": "0!important", "background-color": "#ffffff", "border-radius": "10px"},
            "icon": {"color": "#00C853", "font-size": "16px"}, 
            "nav-link": {"font-size": "14px", "text-align": "center", "margin": "0px", "--hover-color": "#e8f5e9"},
            "nav-link-selected": {"background-color": "#00C853"},
        }
    )
    
    # Map translated menu items back to internal keys if needed, OR just string match
    # Since we are using translations, the `selected_action` variable holds the translated string.
    # We should normalize this or use logic that checks against the Translation dict.
    
    # Helper to check selection
    def is_selected(key):
        return selected_action == TR(key)

    # --- RESET Review State on Tab Change ---
    if 'last_selected_action' not in st.session_state:
        st.session_state.last_selected_action = selected_action
        st.session_state.review_mode = False
        st.session_state.review_data = {}

    if st.session_state.last_selected_action != selected_action:
        st.session_state.review_mode = False
        st.session_state.review_data = {}
        st.session_state.last_selected_action = selected_action

    if is_selected("send"):
        if not st.session_state.review_mode:
            st.subheader(TR("send"))
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                receiver_phone = st.text_input(TR("receiver_phone"), key="send_ph")
            with col_s2:
                send_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=5.0, key="send_amt")
            
            send_desc = st.text_input(TR("desc"), key="send_desc")

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
                     if st.button("Cancel", width="stretch"):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm Transfer", type="primary", width="stretch"):
                         success, msg = transaction_manager.transfer(current_user.phone, data['receiver_phone'], data['amount'], data['desc'])
                         if success:
                             st.success(f"Success! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(2)
                             st.rerun()
                         else:
                             st.error(f"Error: {msg}")

    elif is_selected("request"):
        st.subheader(TR("request"))
        
        with st.form("req_form"):
            target_phone = st.text_input(f"{TR('phone')} ({TR('payer')})")
            req_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0)
            req_desc = st.text_input(TR("desc"))
            
            if st.form_submit_button(TR("request"), type="primary"):
                if target_phone == current_user.phone:
                    st.error("Cannot request from yourself.")
                elif not user_manager.get_user(target_phone):
                    st.error("User not found.")
                else:
                    success, msg = transaction_manager.request_money(current_user.phone, target_phone, req_amount, req_desc)
                    if success:
                        st.success(f"{TR('success')}! {msg}")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"{TR('error')}: {msg}")

    elif is_selected("pay_bills"):
        if not st.session_state.review_mode:
            st.subheader(TR("pay_bills"))
            
            bill_type = st.selectbox("Select Biller Category", ["Airtime & Data", "Electricity (Prepaid)", "Water Utility", "Internet Subscription"])
            
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if bill_type == "Airtime & Data":
                    biller_id = st.text_input(TR("phone"), value=current_user.phone)
                    biller_name = "Telecel/Lonestar"
                elif bill_type == "Electricity (Prepaid)":
                    biller_id = st.text_input("Meter Number")
                    biller_name = "LEC Power"
                else:
                    biller_id = st.text_input("Account/customer ID")
                    biller_name = "Utility Provider"
                    
            with col_b2:
                bill_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=5.0)
                
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
                        <span class="conf-label">{TR('amount')}</span><br/>
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
                     if st.button(TR("cancel"), width="stretch"):
                         st.session_state.review_mode = False
                         st.rerun()
                 with col_btn2:
                     if st.button(TR("confirm"), type="primary", width="stretch"):
                         success, msg = transaction_manager.pay_bill(current_user.phone, data['amount'], data['biller_name'], data['biller_id'], data['desc'])
                         if success:
                             st.success(f"{TR('success')}! {msg}")
                             st.session_state.review_mode = False
                             time.sleep(2)
                             st.rerun()
                         else:
                             st.error(f"{TR('error')}: {msg}")

    elif is_selected("inbox"):
        st.subheader(TR("inbox"))
        
        tab_req, tab_notif = st.tabs([TR("request"), TR("notifications")])
        
        with tab_req:
            # Filter for pending requests where current user is the Payer (Sender)
            pending_requests = [
                t for t in transaction_manager.transactions 
                if t.sender_phone == current_user.phone 
                and t.type == "REQUEST" 
                and t.status == "PENDING"
            ]
            
            if not pending_requests:
                st.info("No pending requests.")
            else:
                for req in pending_requests:
                    with st.container():
                         requester = user_manager.get_user(req.receiver_phone)
                         req_name = requester.name if requester else "Unknown"
                         
                         st.markdown(f"""
                         <div style="border: 1px solid #ddd; padding: 15px; border-radius: 8px; margin-bottom: 7px;">
                            <div style="font-weight: bold;">Request from {req_name} ({req.receiver_phone})</div>
                            <div style="font-size: 1.25em; color: #d9534f;">${req.amount:,.2f}</div>
                            <div style="color: gray; font-style: italic;">"{req.description}"</div>
                            <div style="font-size: 0.8em; color: #888;">{req.timestamp}</div>
                         </div>
                         """, unsafe_allow_html=True)
                         
                         col_act1, col_act2 = st.columns(2)
                         with col_act1:
                             if st.button(TR("pay_bills").split()[0], key=f"pay_{req.id}", type="primary", width="stretch"): # "Pay"
                                 success, msg = transaction_manager.process_request(req.id, "PAY")
                                 if success:
                                     st.success(f"{TR('success')}! {msg}")
                                     time.sleep(1)
                                     st.rerun()
                                 else:
                                     st.error(f"{TR('error')}: {msg}")
                         with col_act2:
                             if st.button(TR("cancel"), key=f"dec_{req.id}", width="stretch"): # Decline/Cancel
                                 success, msg = transaction_manager.process_request(req.id, "DECLINE")
                                 if success:
                                     st.info("Request Declined")
                                     time.sleep(1)
                                     st.rerun()
                                 else:
                                     st.error(f"{TR('error')}: {msg}")
                         st.divider()

        with tab_notif:
            all_tx = transaction_manager.get_history(current_user.phone)
            notifications = []
            
            # Derive alerts
            for t in all_tx:
                if t.receiver_phone == current_user.phone and t.type == "TRANSFER":
                    notifications.append({
                        "time": t.timestamp,
                        "title": "Money Received",
                        "msg": f"You received {t.currency} {t.amount:,.2f} from {t.sender_phone}",
                        "icon": "fa-arrow-down",
                        "color": "#5cb85c"
                    })
                elif t.type == "BILL_PAYMENT" and t.sender_phone == current_user.phone:
                    notifications.append({
                        "time": t.timestamp,
                        "title": "Bill Paid",
                        "msg": f"Payment of {t.currency} {t.amount:,.2f} for {t.description} successful.",
                        "icon": "fa-receipt",
                        "color": "gray"
                    })
                elif t.type == "DEPOSIT" and t.sender_phone == "SYSTEM": 
                     if t.receiver_phone == current_user.phone: # It's a credit
                         notifications.append({
                            "time": t.timestamp,
                            "title": "Deposit Successful",
                            "msg": f"Your account was credited with {t.currency} {t.amount:,.2f}.",
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


    elif is_selected("load"):
        if not st.session_state.review_mode:
            st.subheader(TR("load"))
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
                dep_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=100.0, key="dep_u")
                
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
             st.subheader(TR("confirm"))
             
             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Source</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: #333;">Linked Bank Card</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">{TR('amount')}</span><br/>
                        <span class="conf-amount">${data['amount']:,.2f}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)
                 
                 st.write("")
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button(TR("cancel"), width="stretch"):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button(f"{TR('confirm')} & {TR('load')}", type="primary", width="stretch"):
                         success, msg = transaction_manager.deposit(current_user.phone, data['amount'], data['desc'])
                         if success:
                             st.success(f"{TR('success')}! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(1)
                             st.rerun()
                         else:
                             st.error(f"{TR('error')}: {msg}")
    
    elif is_selected("withdraw"):
        if not st.session_state.review_mode:
            st.subheader(TR("withdraw"))
            with_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=10.0, key="with_u")
            with_desc = st.text_input(f"{TR('desc')} (Optional)", key="with_desc")
            
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
             st.subheader(TR("confirm"))
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
                        <span class="conf-label">{TR('amount')}</span><br/>
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
                     if st.button(TR("cancel"), key="w_can", width="stretch"):
                         st.session_state.review_mode = False
                         st.rerun()
                 with col_btn2:
                     if st.button(f"{TR('confirm')} {TR('withdraw')}", type="primary", width="stretch"):
                         success, msg = transaction_manager.withdraw(current_user.phone, data['amount'], data['desc'])
                         if success:
                             st.success(f"{TR('success')}! {msg}")
                             st.session_state.review_mode = False
                             st.session_state.review_data = {}
                             time.sleep(1)
                             st.rerun()
                         else:
                             st.error(f"{TR('error')}: {msg}")


    elif is_selected("settings"):
        st.subheader(TR("settings"))
        
        with st.form("settings_form"):
            st.markdown("### Update Profile")
            new_name = st.text_input("Full Name", value=current_user.name)
            new_pin = st.text_input(f"New {TR('pin')} (Leave blank to keep current)", type="password", max_chars=4)
            
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
                        st.success(f"{TR('success')}! {msg}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"{TR('error')}: {msg}")
    
    elif is_selected("verify_id"):
        st.subheader(TR("verify_id"))
        if current_user.is_verified:
            st.success("✅ Your identity has been verified.")
            st.info(f"ID Type: {current_user.id_type.upper()}")
            st.info(f"ID Number: {current_user.id_number}")
        else:
            st.warning("Your identity is not yet verified. Transaction limits may apply.")
            with st.form("kyc_form"):
                id_type = st.selectbox("Document Type", ["passport", "national_id"])
                id_number = st.text_input("Document Number")
                
                if st.form_submit_button("Submit for Verification"):
                    if not id_number:
                        st.error("Please enter your ID number.")
                    else:
                        success, msg = user_manager.submit_kyc(current_user.phone, id_type, id_number)
                        if success:
                            st.success(f"{TR('success')}! {msg}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"{TR('error')}: {msg}")



    elif is_selected("history"):
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
Amount: {t.currency} {t.amount:,.2f}
Detail: {detail_text}
Sender: {sender_name} ({t.sender_phone})
Receiver: {receiver_name} ({t.receiver_phone})
Status: Successful
---------------------------"""

                # Custom HTML Transaction Card via CSS Class
                # Check style details
                amt_class = "credit" if badge == "CREDIT" else "debit"
                
                with st.expander(f"{detail_text}", expanded=False):
                    st.markdown(f"""
                    <div class="tx-card">
                        <div class="tx-icon" style="color: {color}; background-color: {color}15;">
                            <i class="{icon}"></i>
                        </div>
                        <div class="tx-details">
                            <div style="font-weight: 500; color: #333;">{detail_text}</div>
                            <div style="font-size: 0.8rem; color: #888;">{t.timestamp.replace('T', ' ')[:16]}</div>
                        </div>
                        <div class="tx-amount {amt_class}">
                            {'+' if badge=='CREDIT' else '-'} {t.currency} {t.amount:,.2f}
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


    elif is_selected("verify_id"):
        st.subheader(TR("verify_id"))
        if current_user.is_verified:
            st.success(f"✅ {TR('success')} - Verified")
            st.info(f"Verified ID Type: {current_user.id_type}")
        else:
            st.info(f"{TR('kyc_needed')}")
            with st.form("kyc_form"):
                id_type = st.selectbox("ID Type", ["Passport", "National ID"])
                id_number = st.text_input("ID Number")
                
                # Mock Upload
                id_file = st.file_uploader("Upload ID Image", type=["jpg", "png", "pdf"])
                
                submitted = st.form_submit_button(TR("confirm"))
                if submitted:
                    if id_number and id_file:
                        success, msg = user_manager.submit_kyc(current_user.phone, id_type.lower().replace(" ", "_"), id_number)
                        if success:
                            st.success(f"{TR('success')}! {msg}")
                            time.sleep(1)
                            st.rerun() 
                        else:
                            st.error(f"{TR('error')}: {msg}")
                    else:
                        st.error("Please provide ID Number and upload a document.")
