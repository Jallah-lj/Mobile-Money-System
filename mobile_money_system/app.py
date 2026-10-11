import contextlib
import csv
import datetime
import html
import os
import re
import time
from decimal import Decimal
from io import StringIO

import streamlit as st
from analytics import budget_status, monthly_statement, monthly_totals, spending_by_category, top_counterparties
from audit import get_audit_logs
from backup import BackupManager
from beneficiaries import BeneficiaryManager
from i18n import get_text
from logging_config import log_structured, setup_logging
from models import utcnow
from notifications import NotificationService
from pdfdoc import build_pdf, receipt_pdf
from privacy import PrivacyManager, export_to_csv
from reconcile import ReconciliationManager
from retention import RetentionManager
from scheduled import ScheduledPaymentManager, start_scheduler
from sessions import SessionManager
from streamlit_option_menu import option_menu
from styles import get_custom_css
from tickets import TicketManager
from transactions import BILL_FEE, TRANSFER_FEE_RATE, WITHDRAWAL_FEE_RATE, TransactionManager
from users import HIGH_VALUE_STEPUP_THRESHOLD, UserManager
from webhooks import WebhookManager


def validate_phone(phone):
    # Allow optional '+', and 7-15 digits for global compatibility
    return re.match(r'^\+?[\d\s\-]{7,15}$', phone)

# --- Configuration & Styles ---
st.set_page_config(
    page_title="Mobile Money System",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply Custom CSS (theme follows the dark-mode toggle)
st.markdown(get_custom_css(dark=st.session_state.get("dark_mode", False)), unsafe_allow_html=True)

# --- Language Setup ---
if 'language' not in st.session_state:
    st.session_state.language = "en"

# --- Appearance (dark mode) ---
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

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

    st.markdown("---")
    dark = st.toggle(TR("dark_mode"), value=st.session_state.dark_mode, key="dark_mode_toggle")
    if dark != st.session_state.dark_mode:
        st.session_state.dark_mode = dark
        st.rerun()

# Component styles live in styles.py (light & dark themes).

# --- State Management ---
if 'user_manager' not in st.session_state:
    st.session_state.user_manager = UserManager()

if 'transaction_manager' not in st.session_state:
    st.session_state.transaction_manager = TransactionManager(st.session_state.user_manager)

if 'session_manager' not in st.session_state:
    st.session_state.session_manager = SessionManager()

if 'beneficiary_manager' not in st.session_state:
    st.session_state.beneficiary_manager = BeneficiaryManager(st.session_state.user_manager)

if 'scheduled_manager' not in st.session_state:
    st.session_state.scheduled_manager = ScheduledPaymentManager(
        st.session_state.user_manager, st.session_state.transaction_manager)

if 'webhook_manager' not in st.session_state:
    st.session_state.webhook_manager = WebhookManager()

if 'notification_service' not in st.session_state:
    st.session_state.notification_service = NotificationService(st.session_state.user_manager)

if 'ticket_manager' not in st.session_state:
    st.session_state.ticket_manager = TicketManager()

if 'privacy_manager' not in st.session_state:
    st.session_state.privacy_manager = PrivacyManager()

if 'backup_manager' not in st.session_state:
    st.session_state.backup_manager = BackupManager()

if 'reconcile_manager' not in st.session_state:
    st.session_state.reconcile_manager = ReconciliationManager()

if 'retention_manager' not in st.session_state:
    st.session_state.retention_manager = RetentionManager()

if 'current_user_phone' not in st.session_state:
    st.session_state.current_user_phone = None

user_manager = st.session_state.user_manager
transaction_manager = st.session_state.transaction_manager
session_manager = st.session_state.session_manager
beneficiary_manager = st.session_state.beneficiary_manager
scheduled_manager = st.session_state.scheduled_manager
webhook_manager = st.session_state.webhook_manager
notification_service = st.session_state.notification_service
ticket_manager = st.session_state.ticket_manager
privacy_manager = st.session_state.privacy_manager
backup_manager = st.session_state.backup_manager
reconcile_manager = st.session_state.reconcile_manager
retention_manager = st.session_state.retention_manager

# --- Structured operational logging (JSON lines to logs/mms.log) ---
setup_logging()
log_structured("APP_BOOT", db_path=os.environ.get("MMS_DB_PATH", "mobile_money.db"))

# --- Scheduler tick: execute due scheduled/standing-order payments ---
# Rows are claimed atomically before execution, so running this on every app
# run is safe and can never double-fire a payment. A process-global
# background thread also ticks on a timer (MMS_SCHEDULER_TICK_SECONDS, default
# 60s; set to 0 to disable) so standing orders fire even when the app is idle.
scheduled_manager.process_due()
if os.environ.get("MMS_AUTO_BACKUP", "1") == "1":
    backup_manager.maybe_auto_backup()
start_scheduler(scheduled_manager,
                tick_seconds=float(os.environ.get("MMS_SCHEDULER_TICK_SECONDS", "60")))

# --- Integration listeners: webhooks + out-of-app notifications ---
# Wired once per session; listeners must never break a transaction.
if 'integrations_wired' not in st.session_state:
    _wm = st.session_state.webhook_manager
    _ns = st.session_state.notification_service

    def _on_transaction_event(event, payload):
        with contextlib.suppress(Exception):
            _wm.dispatch(event, payload)
        with contextlib.suppress(Exception):
            _ns.notify(event, payload)

    transaction_manager.event_listeners.append(_on_transaction_event)
    st.session_state.integrations_wired = True

# Refresh user object from manager to get latest balance
current_user = None
if st.session_state.current_user_phone:
    current_user = user_manager.get_user(st.session_state.current_user_phone)

# --- Helper Functions ---


def logout_user():
    if st.session_state.get('session_token'):
        session_manager.revoke(st.session_state.session_token)
        del st.session_state.session_token
    st.session_state.current_user_phone = None
    if 'otp_verified' in st.session_state:
        del st.session_state.otp_verified
    st.rerun()

# --- Idle session timeout: auto-logout after 15 minutes without activity ---
SESSION_TIMEOUT_SECONDS = 15 * 60
if st.session_state.current_user_phone:
    last_activity = st.session_state.get('last_activity', time.time())
    if time.time() - last_activity > SESSION_TIMEOUT_SECONDS:
        st.session_state.session_expired_notice = True
        logout_user()
    st.session_state.last_activity = time.time()

# --- Server-side session validation: a revoked session ends the login ---
if st.session_state.current_user_phone:
    _token = st.session_state.get('session_token')
    if not _token:
        # First run after login (or a seeded/test session): create the record
        _token = session_manager.create_session(st.session_state.current_user_phone)
        st.session_state.session_token = _token
    elif not session_manager.is_session_valid(_token, st.session_state.current_user_phone):
        st.session_state.session_expired_notice = True
        logout_user()
    else:
        session_manager.touch(_token)

# --- Application Layout ---

st.markdown(f"""
<style>
@media (max-width: 768px) {{
    .app-title {{
        font-size: 1.8rem !important;
    }}
}}
</style>
<h1 class="app-title" style="text-align: center; color: var(--mms-primary-deep);"><i class="fa-solid fa-money-bill-transfer"></i> {TR('app_title')}</h1>
""", unsafe_allow_html=True)

if not current_user:
    # --- Auth View ---
    st.markdown(f"<h3 style='text-align: center; margin-bottom: 2rem;'>{html.escape(TR('welcome'))}</h3>", unsafe_allow_html=True)
    if st.session_state.get('session_expired_notice'):
        st.warning(TR("session_expired"))
        del st.session_state.session_expired_notice
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        selected = option_menu(
            menu_title=None,
            options=[TR("login"), TR("register")],
            key="auth_nav",
            icons=["box-arrow-in-right", "person-plus"],
            menu_icon="cast",
            default_index=0,
            orientation="horizontal",
            styles={
                "container": {"background-color": "transparent"},
                "nav-link": {"font-size": "14px", "color": "var(--mms-text)"},
                "nav-link-selected": {"background-color": "#007a1e"},
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
                                if user.two_factor_enabled:
                                    # Move to OTP Stage
                                    st.session_state.login_stage = 'otp'
                                    st.session_state.temp_phone = phone
                                    st.session_state.temp_pin = pin # Keep temporarily
                                    st.rerun()
                                else:
                                    # 2FA disabled for this account — log straight in
                                    st.session_state.current_user_phone = user.phone
                                    st.session_state.session_token = session_manager.create_session(user.phone)
                                    st.rerun()
                            else:
                                st.error("Invalid Phone Number or PIN")
                        else:
                            st.warning("Please enter both Phone and PIN")

            elif st.session_state.login_stage == 'otp':
                st.markdown("### <i class='fa-solid fa-shield-halved'></i> 2FA Verification", unsafe_allow_html=True)
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
                            # Success: Log in (canonical phone + session record)
                            logged_in_user = user_manager.get_user(st.session_state.temp_phone) \
                                or user_manager.get_user(user_manager.format_phone(st.session_state.temp_phone))
                            st.session_state.current_user_phone = logged_in_user.phone if logged_in_user else st.session_state.temp_phone
                            st.session_state.session_token = session_manager.create_session(st.session_state.current_user_phone)
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
                        st.error("Invalid Phone Number (Use international format e.g., +234...)")
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

        st.markdown("## <i class='fa-solid fa-layer-group'></i> System Administration", unsafe_allow_html=True)

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
            key="admin_nav",
            options=["Users", "Transactions", "Bills & Revenue", "Security", "Audit", "Analytics", "System", "Support"],
            icons=["people", "cash-coin", "receipt", "shield-lock", "clipboard-list", "graph-up", "gear", "headset"],
            default_index=0,
            orientation="horizontal",
            styles={"nav-link": {"font-size": "14px", "color": "var(--mms-text)"}}
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
                        if risk_tier != target_u.risk_tier and st.button("Update Risk Tier", width="stretch"):
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

            st.markdown("### Pending Account Deletion Requests")
            pending_dels = privacy_manager.pending_deletions()
            if not pending_dels:
                st.info("No pending deletion requests.")
            else:
                for dr in pending_dels:
                    with st.expander(f"Request #{dr['id']} \u2014 {dr['phone']} ({dr['requested_at'].replace('T', ' ')[:16]})"):
                        st.write("**Reason:** " + str(dr['reason'] or "—"))
                        col_d1, col_d2 = st.columns(2)
                        with col_d1:
                            if st.button("Approve Deletion", type="primary", key=f"del_ok_{dr['id']}"):
                                ok, msg = privacy_manager.approve_deletion(dr["id"], current_user.phone)
                                if ok:
                                    st.success(msg)
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(msg)
                        with col_d2:
                            note = st.text_input("Rejection note", key=f"del_no_{dr['id']}")
                            if st.button("Reject", key=f"del_rj_{dr['id']}"):
                                ok, msg = privacy_manager.reject_deletion(dr["id"], current_user.phone, note)
                                if ok:
                                    st.success(msg)
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(msg)

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
                 col_rev1, col_rev2 = st.columns(2)
                 col_rev1.metric("Total Fee Revenue", f"${total_rev:,.2f}")
                 col_rev2.metric("Revenue Transactions", len(revenue_tx))
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

        # ---------------- AUDIT TAB ----------------
        elif selected_adm == "Audit":
            st.subheader(f"📜 {TR('audit_log')}")
            st.caption("Append-only compliance trail of every security-relevant event.")
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                audit_action = st.text_input("Filter by Action", placeholder="e.g. LOGIN_FAILURE, TRANSFER")
            with col_f2:
                audit_actor = st.text_input("Filter by Actor (phone)")
            with col_f3:
                audit_limit = st.slider("Entries", 50, 1000, 200)

            logs = get_audit_logs(limit=audit_limit, actor_phone=audit_actor or None,
                                  action=audit_action or None)
            if not logs:
                st.info("No audit entries found.")
            else:
                st.dataframe([e.to_dict() for e in logs], width="stretch")
                csv_buf = StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=["id", "timestamp", "actor_phone", "action", "target", "details", "status"])
                writer.writeheader()
                for e in logs:
                    writer.writerow(e.to_dict())
                st.download_button("Download Audit CSV", data=csv_buf.getvalue(),
                                   file_name="audit_log.csv", mime="text/csv")

        # ---------------- ANALYTICS TAB ----------------
        elif selected_adm == "Analytics":
            st.subheader("📊 Reports & Analytics")
            st.info("Export data for external analysis.")

            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                st.markdown("**User Data**")
                users_csv = StringIO()
                all_users = list(user_manager.users.values())
                if all_users:
                    writer = csv.DictWriter(users_csv, fieldnames=list(all_users[0].to_public_dict().keys()))
                    writer.writeheader()
                    for u in all_users:
                        writer.writerow(u.to_public_dict())
                st.download_button("Download Users CSV", data=users_csv.getvalue(),
                                   file_name="users.csv", mime="text/csv")
            with col_exp2:
                st.markdown("**Transaction Logs**")
                tx_csv = StringIO()
                all_tx = transaction_manager.transactions
                if all_tx:
                    writer = csv.DictWriter(tx_csv, fieldnames=list(all_tx[0].to_dict().keys()))
                    writer.writeheader()
                    for t in all_tx:
                        writer.writerow(t.to_dict())
                st.download_button("Download Transactions CSV", data=tx_csv.getvalue(),
                                   file_name="transactions.csv", mime="text/csv")

            st.markdown("### Daily Transaction Volume")
            from collections import Counter
            daily = Counter(t.timestamp[:10] for t in transaction_manager.transactions)
            if daily:
                st.bar_chart(daily)
            else:
                st.info("No transaction data yet.")

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

            st.markdown("---")
            st.markdown("### Webhooks (Event Integrations)")
            st.caption("Signed (HMAC-SHA256) JSON push of transaction events to external systems.")
            with st.form("webhook_form"):
                wh_name = st.text_input("Name", placeholder="e.g. My ERP")
                wh_url = st.text_input("URL", placeholder="https://example.com/hook")
                wh_events = st.multiselect("Events", ["TRANSFER", "DEPOSIT", "WITHDRAWAL", "BILL_PAYMENT", "REQUEST"],
                                           default=["TRANSFER"])
                wh_secret = st.text_input("Signing Secret (leave blank to auto-generate)", type="password")
                if st.form_submit_button("Add Webhook"):
                    ok, msg = webhook_manager.add(wh_name, wh_url, wh_events, wh_secret or None)
                    if ok:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
            hooks = webhook_manager.list()
            if hooks:
                for h in hooks:
                    col_w1, col_w2, col_w3 = st.columns([3, 3, 1])
                    with col_w1:
                        st.write(f"**{h['name']}** — {h['url']}")
                    with col_w2:
                        st.caption(f"Events: {h['events']} • {'active' if h['active'] else 'inactive'}")
                    with col_w3:
                        if st.button("Delete", key=f"wh_del_{h['id']}"):
                            webhook_manager.remove(h['id'])
                            st.rerun()
                with st.expander("Recent Deliveries"):
                    deliveries = webhook_manager.recent_deliveries(limit=100)
                    if deliveries:
                        st.dataframe([{k: d[k] for k in ("id", "webhook_id", "event", "status_code", "attempts", "delivered_at", "error")} for d in deliveries],
                                     width="stretch")
                    else:
                        st.info("No deliveries yet.")
            else:
                st.info("No webhooks registered yet.")

            st.markdown("---")
            st.markdown("### 💾 Backups")
            st.caption("Snapshots of the whole database (SQLite online backup — safe while the app is running). "
                       "Automatic snapshots are taken at most once per configured interval.")
            col_bk1, col_bk2 = st.columns([1, 3])
            with col_bk1:
                if st.button("📸 Create Backup Now", width="stretch"):
                    ok, result = backup_manager.create_backup(note="manual")
                    if ok:
                        st.success(f"Backup created: {os.path.basename(result)}")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(result)
            with col_bk2:
                backups = backup_manager.list_backups()
                if backups:
                    for b in backups:
                        col_b1, col_b2, col_b3 = st.columns([3, 2, 2])
                        with col_b1:
                            st.write(f"**{b['filename']}** — {b['size_bytes'] / 1024:.1f} KB — {b['created_at'].replace('T', ' ')[:16]}"
                                     + (f" — {b['note']}" if b['note'] else ""))
                        with col_b2:
                            path = backup_manager.backup_path(b['filename'])
                            if path:
                                with open(path, "rb") as fh:
                                    st.download_button("Download", fh.read(),
                                                       file_name=b['filename'],
                                                       mime="application/octet-stream",
                                                       key=f"bk_dl_{b['id']}")
                        with col_b3:
                            if st.button("Restore", key=f"bk_rs_{b['id']}", type="primary"):
                                ok, msg = backup_manager.restore_backup(b['filename'])
                                if ok:
                                    st.success(msg)
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(msg)
                else:
                    st.info("No backups yet.")

            st.markdown("---")
            st.markdown("### 🔍 Ledger Reconciliation")
            st.caption("Verifies every user balance against the double-entry ledger and checks money conservation.")
            if st.button("Run Reconciliation", width="stretch"):
                report = reconcile_manager.reconcile()
                st.session_state.recon_report = report
            report = st.session_state.get("recon_report")
            if report:
                col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                col_r1.metric("Users Checked", report["checked_users"])
                col_r2.metric("Balance Mismatches", len(report["balance_mismatches"]))
                col_r3.metric("Unbalanced Txns", len(report["unbalanced_transactions"]))
                col_r4.metric("Users Total", f"${float(report['users_total']):,.2f}")
                if report["ok"]:
                    st.success("Reconciliation passed: balances match the ledger and money is conserved.")
                else:
                    st.error("Reconciliation found problems — see below.")
                if report["balance_mismatches"]:
                    st.markdown("**Balance mismatches**")
                    st.dataframe(report["balance_mismatches"], width="stretch")
                if report["unbalanced_transactions"]:
                    st.markdown("**Unbalanced ledger batches**")
                    st.dataframe(report["unbalanced_transactions"], width="stretch")

            st.markdown("---")
            st.markdown("### 🧹 Data Retention")
            st.caption("Prunes old rows (audit log, sessions, deliveries, OTPs, rate-limit hits, idempotency keys, lockouts) "
                       "according to the retention periods below. Days; 0 = keep forever.")
            from config import all_settings, get_setting, set_setting
            settings = all_settings()
            ret_keys = [
                ("retention_days_audit_log", "Audit log"),
                ("retention_days_sessions", "Sessions"),
                ("retention_days_webhook_deliveries", "Webhook deliveries"),
                ("retention_days_login_attempts", "Login attempts"),
                ("retention_days_misc", "OTPs & rate-limit hits"),
                ("retention_days_idempotency_keys", "Idempotency keys"),
                ("retention_days_account_lockouts", "Account lockouts"),
            ]
            ret_cols = st.columns(4)
            for i, (key, label) in enumerate(ret_keys):
                with ret_cols[i % 4]:
                    st.number_input(label + " (days)", min_value=0, max_value=3650,
                                    value=int(settings.get(key, 0)), key=f"ret_{key}")
            col_rt1, col_rt2 = st.columns([1, 3])
            with col_rt1:
                if st.button("Save Retention", width="stretch"):
                    for key, _label in ret_keys:
                        set_setting(key, str(st.session_state[f"ret_{key}"]))
                    st.success("Retention settings saved")
                    time.sleep(1)
                    st.rerun()
            with col_rt2:
                last_run = get_setting("retention_last_run", "never")
                st.caption(f"Last run: {last_run.replace('T', ' ')[:19]}")
            if st.button("🧹 Run Retention Now", width="stretch"):
                deleted = retention_manager.run_retention()
                total = sum(deleted.values())
                log_structured("RETENTION_RUN", deleted=deleted)
                st.success(f"Retention complete — {total} old rows removed.")
                time.sleep(1)
                st.rerun()

            st.markdown("---")
            st.markdown("### 📊 Operations")
            from database import get_db as _get_db
            with _get_db() as _conn:
                _journal = _conn.execute("PRAGMA journal_mode").fetchone()[0]
                _users = _conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                _txns = _conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            st.caption(f"Database: {os.environ.get('MMS_DB_PATH', 'mobile_money.db')} • "
                       f"journal mode: {_journal} • users: {_users} • transactions: {_txns}")

        # ---------------- SUPPORT TAB ----------------
        elif selected_adm == "Support":
            st.subheader("🧑‍💼 Agent Support Console")

            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                f_status = st.selectbox("Status", ["All", "open", "in_progress", "resolved", "closed"], key="adm_tk_status")
            with col_f2:
                f_cat = st.selectbox("Category", ["All", "payment", "account", "kyc", "security", "other"], key="adm_tk_cat")
            with col_f3:
                st.metric("Total Tickets", len(ticket_manager.all_tickets()))

            tickets = ticket_manager.all_tickets(
                status=None if f_status == "All" else f_status,
                category=None if f_cat == "All" else f_cat)
            if not tickets:
                st.info("No tickets match the filters.")
            else:
                st.dataframe([{k: t[k] for k in ("id", "phone", "subject", "category", "status", "priority", "created_at")} for t in tickets],
                             width="stretch")

                st.markdown("### Work a Ticket")
                sel_id = st.selectbox("Select Ticket", [t["id"] for t in tickets],
                                      format_func=lambda i: f"#{i} — {next(t['subject'] for t in tickets if t['id'] == i)}",
                                      key="adm_tk_sel")
                tk = ticket_manager.get(sel_id)
                user = user_manager.get_user(tk["phone"])
                st.markdown(f"**From:** {user.name if user else 'Unknown'} ({tk['phone']})")
                st.markdown(f"**Category:** {tk['category']} • **Priority:** {tk['priority']} • **Status:** {tk['status']}")
                st.markdown(f"**Subject:** {tk['subject']}")
                st.info(tk["message"])
                if tk["admin_reply"]:
                    st.success(f"Last reply ({tk['replied_at'].replace('T', ' ')[:16]} by {tk['replied_by']}): {tk['admin_reply']}")
                reply_text = st.text_area("Reply to user", key="adm_tk_reply")
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    if st.button("Send Reply", type="primary", key="adm_tk_send"):
                        ok, msg = ticket_manager.reply(tk["id"], current_user.phone, reply_text)
                        if ok:
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                with col_r2:
                    new_status = st.selectbox("Set Status", ["open", "in_progress", "resolved", "closed"],
                                              index=["open", "in_progress", "resolved", "closed"].index(tk["status"]),
                                              key="adm_tk_status_set")
                    if new_status != tk["status"] and st.button("Update Status", key="adm_tk_upd"):
                        ok, msg = ticket_manager.set_status(tk["id"], new_status, actor_phone=current_user.phone)
                        if ok:
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

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
            <i class="fa-solid fa-circle-user fa-5x" style="color: var(--mms-primary-deep);"></i>
            <h3>{current_user.name}</h3>
            <p style="color: var(--mms-muted);"><i class="fa-solid fa-phone"></i> {current_user.phone}</p>
        </div>
        """, unsafe_allow_html=True)

        # QR Code Display
        try:
            import base64
            from io import BytesIO

            import qrcode

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
                <p style='font-size: 0.8em; color: var(--mms-muted);'>Scan to Request/Pay</p>
                <img src="data:image/png;base64,{img_str}" width="150" alt="QR code for {current_user.phone} — scan to pay or request" />
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

    # Wallet Card
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
    nav_options = [TR("send"), TR("request"), TR("pay_bills"), TR("load"), TR("withdraw"), TR("inbox"), TR("history"), TR("scheduled"), TR("insights"), TR("support"), TR("settings"), TR("verify_id")]
    nav_icons = ["send", "arrow-left-circle", "receipt", "credit-card", "arrow-up-circle", "envelope", "clock-history", "calendar-check", "graph-up", "headset", "gear", "card-heading"]
    # Theme-aware nav colors: the icon must pass AA on the themed container
    # (bright green in dark mode, deep green in light mode).
    nav_icon_color = "#00e676" if st.session_state.get("dark_mode", False) else "#007a1e"
    selected_action = option_menu(
        menu_title=None,
        key="main_nav",
        options=nav_options,
        icons=nav_icons,
        default_index=0,
        orientation="horizontal",
        styles={
            "container": {"padding": "0!important", "background-color": "var(--mms-surface)", "border": "1px solid var(--mms-border)", "border-radius": "10px"},
            "icon": {"color": nav_icon_color, "font-size": "16px"},
            "nav-link": {"font-size": "14px", "text-align": "center", "margin": "0px", "color": "var(--mms-text)", "--hover-color": "var(--mms-primary-soft)"},
            "nav-link-selected": {"background-color": "#007a1e"},
        }
    )

    # Map translated menu items back to internal keys if needed, OR just string match
    # Since we are using translations, the `selected_action` variable holds the translated string.
    # We should normalize this or use logic that checks against the Translation dict.

    # Helper to check selection
    def is_selected(key):
        return selected_action == TR(key)

    def stepup_required(amount) -> bool:
        """True when this debit exceeds the high-value threshold and 2FA is on."""
        if current_user is None or not current_user.two_factor_enabled:
            return False
        try:
            return Decimal(str(amount)) > HIGH_VALUE_STEPUP_THRESHOLD
        except Exception:
            return False

    def render_stepup_challenge():
        """Render the OTP challenge for a high-value debit."""
        st.warning("🔐 High-value transaction — extra verification required.")
        if 'stepup_code' not in st.session_state:
            code = user_manager.generate_otp(current_user.phone)
            st.session_state.stepup_code = code
            st.info(f"Simulation: Your Security Code is **{code}**")
        otp = st.text_input("Security Code", key="stepup_otp_input")
        if st.button("Verify Code", key="stepup_verify_btn"):
            if user_manager.verify_otp(current_user.phone, otp):
                st.session_state.stepup_verified = True
                st.rerun()
            else:
                st.error("Invalid code.")

    # --- RESET Review State on Tab Change ---
    if 'last_selected_action' not in st.session_state:
        st.session_state.last_selected_action = selected_action
        st.session_state.review_mode = False
        st.session_state.review_data = {}

    if st.session_state.last_selected_action != selected_action:
        st.session_state.review_mode = False
        st.session_state.review_data = {}
        st.session_state.stepup_verified = False
        st.session_state.pop('stepup_code', None)
        st.session_state.last_selected_action = selected_action

    if is_selected("send"):
        if not st.session_state.review_mode:
            st.subheader(TR("send"))
            # Saved beneficiaries + recent recipients
            bens = beneficiary_manager.list(current_user.phone)
            recent = [p for p in beneficiary_manager.recent_recipients(current_user.phone, limit=5)
                      if p != current_user.phone and all(b['phone'] != p for b in bens)]
            ben_choices = (["➕ Enter new number"]
                           + [f"⭐ {b['nickname']} ({b['phone']})" for b in bens]
                           + [f"🕒 {p}" for p in recent])
            ben_choice = st.selectbox("Recipient", ben_choices, key="send_ben")
            save_nickname = ""
            col_s1, col_s2 = st.columns(2)
            if ben_choice == "➕ Enter new number":
                with col_s1:
                    receiver_phone = st.text_input(TR("receiver_phone"), key="send_ph")
                with col_s2:
                    send_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=5.0, key="send_amt")
                save_as = st.checkbox("Save as beneficiary", key="send_save_as")
                if save_as:
                    save_nickname = st.text_input("Nickname for this recipient", key="send_nick")
            else:
                receiver_phone = ben_choice.split("(")[-1].rstrip(")")
                with col_s1:
                    st.text_input(TR("receiver_phone"), value=receiver_phone, disabled=True, key="send_ph_ro")
                with col_s2:
                    send_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=5.0, key="send_amt")
                st.caption(f"Saved beneficiary — {receiver_phone}")

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
                        st.session_state.send_save_nickname = save_nickname
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

             # Fee Calculation (0% transfer fee — the platform is free to use)
             fee = data['amount'] * float(TRANSFER_FEE_RATE)
             total_deduction = data['amount'] + fee
             fee_label = "0%"

             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Recipient</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: var(--mms-text);">{data['receiver_name']}</span> <br/>
                        <span style="color: var(--mms-muted); font-family: monospace;">{data['receiver_phone']}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Amount</span><br/>
                        <span class="conf-amount" style="color: var(--mms-primary-deep);">${data['amount']:,.2f}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Fee ({fee_label})</span><br/>
                        <span style="font-size: 1.1em; color: var(--mms-muted);">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total Deduction</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: var(--mms-danger);">${total_deduction:,.2f}</span>
                    </div>
                    <div>
                        <span class="conf-label">Reference</span><br/>
                        <span style="font-style: italic;">{data['desc'] if data['desc'] else 'No description'}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)

                 st.write("")
                 if stepup_required(data['amount']) and not st.session_state.get('stepup_verified'):
                     render_stepup_challenge()
                 st.write("")
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button("Cancel", width="stretch"):
                         st.session_state.review_mode = False
                         st.session_state.review_data = {}
                         st.rerun()
                 with col_btn2:
                     if st.button("Confirm Transfer", type="primary", width="stretch"):
                         if stepup_required(data['amount']) and not st.session_state.get('stepup_verified'):
                             st.warning("Please complete the verification above first.")
                         else:
                             success, msg = transaction_manager.transfer(current_user.phone, data['receiver_phone'], data['amount'], data['desc'])
                             if success:
                                 st.success(f"Success! {msg}")
                                 save_nick = st.session_state.get('send_save_nickname', '')
                                 if save_nick:
                                     beneficiary_manager.add(current_user.phone, data['receiver_phone'], save_nick)
                                     st.session_state.send_save_nickname = ''
                                 else:
                                     beneficiary_manager.touch(current_user.phone, data['receiver_phone'])
                                 st.session_state.review_mode = False
                                 st.session_state.review_data = {}
                                 st.session_state.stepup_verified = False
                                 st.session_state.pop('stepup_code', None)
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

             fee = float(BILL_FEE)
             total = data['amount'] + fee
             fee_label = "$0.25"

             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                         <span class="conf-label">Service</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: var(--mms-text);">{data['biller_name']}</span>
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
                         <span class="conf-label">Service Fee ({fee_label})</span><br/>
                        <span style="color: var(--mms-muted);">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total to Pay</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: var(--mms-danger);">${total:,.2f}</span>
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
                         <div style="border: 1px solid var(--mms-border); padding: 15px; border-radius: 8px; margin-bottom: 7px;">
                            <div style="font-weight: bold;">Request from {req_name} ({req.receiver_phone})</div>
                            <div style="font-size: 1.25em; color: var(--mms-danger);">${req.amount:,.2f}</div>
                            <div style="color: var(--mms-muted); font-style: italic;">"{req.description}"</div>
                            <div style="font-size: 0.8em; color: var(--mms-muted);">{req.timestamp}</div>
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
                        "color": "var(--mms-primary-deep)"
                    })
                elif t.type == "BILL_PAYMENT" and t.sender_phone == current_user.phone:
                    notifications.append({
                        "time": t.timestamp,
                        "title": "Bill Paid",
                        "msg": f"Payment of {t.currency} {t.amount:,.2f} for {t.description} successful.",
                        "icon": "fa-receipt",
                        "color": "var(--mms-muted)"
                    })
                elif t.type == "DEPOSIT" and t.sender_phone == "SYSTEM" and t.receiver_phone == current_user.phone:
                    # It's a credit
                    notifications.append({
                        "time": t.timestamp,
                        "title": "Deposit Successful",
                        "msg": f"Your account was credited with {t.currency} {t.amount:,.2f}.",
                        "icon": "fa-wallet",
                        "color": "var(--mms-primary-deep)"
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
                            <div style="color: var(--mms-text); font-size: 0.9em;">{n['msg']}</div>
                            <div style="color: var(--mms-muted); font-size: 0.75em; margin-top: 4px;">{n['time'].replace('T', ' ')[:16]}</div>
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
                        <span style="font-size: 1.2em; font-weight: bold; color: var(--mms-text);">Linked Bank Card</span>
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

             # Calculate Fee (0.5% withdrawal fee)
             fee = data['amount'] * float(WITHDRAWAL_FEE_RATE)
             total_deduction = data['amount'] + fee
             fee_label = "0.5%"

             with st.container():
                 st.markdown(f"""
                 <div class="conf-card">
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Transaction Type</span><br/>
                        <span style="font-size: 1.2em; font-weight: bold; color: var(--mms-danger);">WITHDRAWAL</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">{TR('amount')}</span><br/>
                        <span class="conf-amount">${data['amount']:,.2f}</span>
                    </div>
                    <div style="margin-bottom: 15px;">
                        <span class="conf-label">Fee ({fee_label})</span><br/>
                        <span style="font-size: 1.1em; color: var(--mms-muted);">${fee:,.2f}</span>
                    </div>
                     <div style="margin-bottom: 15px; border-top: 1px dashed #ccc; pt-2;">
                        <span class="conf-label">Total Deduction</span><br/>
                        <span style="font-size: 1.3em; font-weight: bold; color: var(--mms-danger);">${total_deduction:,.2f}</span>
                    </div>
                    <div>
                        <span class="conf-label">Reference</span><br/>
                        <span style="font-style: italic;">{data['desc']}</span>
                    </div>
                 </div>
                 """, unsafe_allow_html=True)

                 st.write("")
                 if stepup_required(data['amount']) and not st.session_state.get('stepup_verified'):
                     render_stepup_challenge()
                 col_btn1, col_btn2 = st.columns(2)
                 with col_btn1:
                     if st.button(TR("cancel"), key="w_can", width="stretch"):
                         st.session_state.review_mode = False
                         st.rerun()
                 with col_btn2:
                     if st.button(f"{TR('confirm')} {TR('withdraw')}", type="primary", width="stretch"):
                         if stepup_required(data['amount']) and not st.session_state.get('stepup_verified'):
                             st.warning("Please complete the verification above first.")
                         else:
                             success, msg = transaction_manager.withdraw(current_user.phone, data['amount'], data['desc'])
                             if success:
                                 st.success(f"{TR('success')}! {msg}")
                                 st.session_state.review_mode = False
                                 st.session_state.review_data = {}
                                 st.session_state.stepup_verified = False
                                 st.session_state.pop('stepup_code', None)
                                 time.sleep(1)
                                 st.rerun()
                             else:
                                 st.error(f"{TR('error')}: {msg}")


    elif is_selected("scheduled"):
        st.subheader("📅 " + TR("scheduled"))
        st.caption("One-off future payments and recurring standing orders. Due payments execute automatically.")

        with st.form("sched_form"):
            sp_type = st.selectbox("Payment Type", ["Transfer to user", "Bill payment"])
            if sp_type == "Transfer to user":
                bens = beneficiary_manager.list(current_user.phone)
                choices = ["Enter phone number"] + [f"{b['nickname']} ({b['phone']})" for b in bens]
                choice = st.selectbox("Recipient", choices, key="sched_recipient")
                if choice == "Enter phone number":
                    receiver_phone = st.text_input(TR("receiver_phone"), key="sched_rx")
                else:
                    receiver_phone = choice.split("(")[-1].rstrip(")")
                biller_name = biller_id = ""
            else:
                receiver_phone = ""
                biller_name = st.text_input("Biller / Provider Name")
                biller_id = st.text_input("Biller Account / ID")
            sp_amount = st.number_input(f"{TR('amount')} ({current_user.currency})", min_value=1.0, step=5.0, key="sched_amt")
            sp_desc = st.text_input(TR("desc"), key="sched_desc")
            sp_freq = st.selectbox("Frequency", ["once", "daily", "weekly", "monthly"], key="sched_freq")
            sp_date = st.date_input("First run date", value=datetime.date.today(), key="sched_date")
            if st.form_submit_button("Schedule Payment", type="primary"):
                start_at = datetime.datetime.combine(sp_date, datetime.time.min).isoformat()
                if sp_type == "Transfer to user":
                    ok, msg = scheduled_manager.create(
                        current_user.phone, "TRANSFER", sp_amount, sp_desc,
                        receiver_phone=receiver_phone, frequency=sp_freq, start_at=start_at)
                else:
                    ok, msg = scheduled_manager.create(
                        current_user.phone, "BILL_PAYMENT", sp_amount, sp_desc,
                        biller_name=biller_name, biller_id=biller_id,
                        frequency=sp_freq, start_at=start_at)
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown("---")
        st.markdown("### Your Scheduled Payments")
        payments = scheduled_manager.list(current_user.phone)
        if not payments:
            st.info("No scheduled payments yet.")
        else:
            for p in payments:
                active = bool(p['active'])
                state = "Active" if active else "Paused/Cancelled"
                if p['type'] == "TRANSFER":
                    target = f"Transfer to {p['receiver_phone']}"
                else:
                    target = f"Bill payment — {p['biller_name']} ({p['biller_id']})"
                with st.container():
                    st.markdown(f"""
                    <div style="border: 1px solid var(--mms-border); padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                        <div style="font-weight: bold; color: var(--mms-text);">{target}</div>
                        <div style="color: var(--mms-text);">Amount: {current_user.currency} {float(p['amount']):,.2f} &nbsp;•&nbsp; Frequency: {p['frequency']}</div>
                        <div style="color: var(--mms-muted); font-size: 0.85em;">Next run: {p['next_run_at'].replace('T', ' ')[:16]} &nbsp;•&nbsp; {state}</div>
                        <div style="color: var(--mms-muted); font-size: 0.85em;">Last: {p['last_status'] or '—'}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if active:
                            if st.button("Pause", key=f"sp_pause_{p['id']}"):
                                scheduled_manager.set_active(current_user.phone, p['id'], False)
                                st.rerun()
                        else:
                            if st.button("Resume", key=f"sp_resume_{p['id']}"):
                                scheduled_manager.set_active(current_user.phone, p['id'], True)
                                st.rerun()
                    with col_b:
                        if st.button("Cancel", key=f"sp_cancel_{p['id']}", type="primary"):
                            scheduled_manager.cancel(current_user.phone, p['id'])
                            st.rerun()

    elif is_selected("insights"):
        st.subheader("📊 " + TR("insights"))
        history = transaction_manager.get_history(current_user.phone)
        if not history:
            st.info("No transactions yet — your insights and statements will appear here once you transact.")
        else:
            now = utcnow()
            year, month = now.year, now.month

            # --- Monthly budget ---
            st.markdown("### Monthly Budget")
            col_bb1, col_bb2, col_bb3 = st.columns(3)
            current_budget = float(current_user.monthly_budget or 0)
            new_budget = col_bb1.number_input("Spending budget (per month)", min_value=0.0,
                                              value=current_budget, step=50.0, key="budget_input")
            if new_budget != current_budget and col_bb2.button("Save Budget", key="budget_save"):
                user_manager.update_user(current_user.phone, monthly_budget=str(new_budget))
                st.success("Budget saved.")
                time.sleep(1)
                st.rerun()
            bs = budget_status(history, current_user.phone, Decimal(str(current_budget)), year, month)
            col_bb1.metric("Spent this month", f"${bs['spent']:,.2f}")
            col_bb2.metric("Budget", f"${current_budget:,.2f}" if current_budget > 0 else "Not set")
            if current_budget > 0:
                col_bb3.metric("Remaining", f"${bs['remaining']:,.2f}",
                               delta=f"{bs['pct']:.0f}% used" if bs['pct'] is not None else None)
                if bs['pct'] is not None and bs['pct'] >= 100:
                    st.error("You have exceeded your monthly budget.")
                elif bs['pct'] is not None and bs['pct'] >= 80:
                    st.warning("You have used 80%+ of your monthly budget.")

            st.markdown("---")
            # --- 6-month income vs spending trend ---
            st.markdown("### Income vs Spending (last 6 months)")
            totals = monthly_totals(history, current_user.phone, months=6)
            import pandas as pd
            trend_df = pd.DataFrame([
                {"Month": t["month"],
                 "Income": float(t["income"]),
                 "Spending": float(t["spending"] + t["fees"])}
                for t in totals
            ])
            st.bar_chart(trend_df.set_index("Month"))

            # --- Category breakdown + top recipients ---
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.markdown("### Spending by Category (this month)")
                cats = spending_by_category(history, current_user.phone, year, month)
                if cats:
                    st.bar_chart({k: float(v) for k, v in
                                  sorted(cats.items(), key=lambda kv: kv[1], reverse=True)})
                else:
                    st.info("No spending this month.")
            with col_c2:
                st.markdown("### Top Recipients (all time)")
                top = top_counterparties(history, current_user.phone, n=5)
                if top:
                    rows = []
                    for r in top:
                        rcpt = user_manager.get_user(r["phone"])
                        rows.append({"Recipient": rcpt.name if rcpt else r["phone"],
                                     "Phone": r["phone"],
                                     "Transfers": r["count"],
                                     "Total Sent": float(r["amount"])})
                    st.dataframe(rows, width="stretch")
                else:
                    st.info("No outgoing transfers yet.")

            st.markdown("---")
            # --- Monthly statement ---
            st.markdown("### Account Statement")
            available_months = sorted({t.timestamp[:7] for t in history}, reverse=True)
            month_choice = st.selectbox("Statement month", available_months, key="stmt_month")
            sy, sm = int(month_choice[:4]), int(month_choice[5:7])
            stmt = monthly_statement(history, current_user.phone, sy, sm)
            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            col_s1.metric("Opening Balance", f"${stmt['opening_balance']:,.2f}")
            col_s2.metric("Money In", f"${stmt['income']:,.2f}")
            col_s3.metric("Money Out", f"${(stmt['spending'] + stmt['fees']):,.2f}")
            col_s4.metric("Closing Balance", f"${stmt['closing_balance']:,.2f}")
            st.caption(f"{stmt['tx_count']} transaction(s) in {month_choice}")
            st.dataframe([t.to_dict() for t in stmt["transactions"]], width="stretch")

            stmt_csv = StringIO()
            if stmt["transactions"]:
                writer = csv.DictWriter(stmt_csv, fieldnames=list(stmt["transactions"][0].to_dict().keys()))
                writer.writeheader()
                for t in stmt["transactions"]:
                    writer.writerow(t.to_dict())
            st.download_button("Download Statement (CSV)", data=stmt_csv.getvalue(),
                               file_name=f"statement_{month_choice}.csv", mime="text/csv", key="stmt_csv")

            stmt_lines = [
                f"Account: {current_user.name} ({current_user.phone})",
                f"Period: {month_choice}",
                f"Opening balance: {current_user.currency} {stmt['opening_balance']:,.2f}",
                f"Money in:        {current_user.currency} {stmt['income']:,.2f}",
                f"Money out:       {current_user.currency} {stmt['spending']:,.2f}",
                f"Fees:            {current_user.currency} {stmt['fees']:,.2f}",
                f"Closing balance: {current_user.currency} {stmt['closing_balance']:,.2f}",
                "",
                "Transactions:",
            ]
            for t in stmt["transactions"]:
                stmt_lines.append(
                    f"{t.timestamp.replace('T', ' ')[:16]}  {t.type:<14} "
                    f"{float(t.amount):>10,.2f}  {t.description or ''}  [{t.status}]")
            st.download_button("Download Statement (PDF)",
                               data=build_pdf(f"ACCOUNT STATEMENT \u2014 {month_choice}", stmt_lines),
                               file_name=f"statement_{month_choice}.pdf",
                               mime="application/pdf", key="stmt_pdf")

    elif is_selected("support"):
        st.subheader("🎧 " + TR("support"))
        st.caption("Having trouble? Open a ticket and our team will get back to you.")

        with st.form("ticket_form"):
            t_subject = st.text_input("Subject")
            t_category = st.selectbox("Category", ["payment", "account", "kyc", "security", "other"])
            t_priority = st.selectbox("Priority", ["low", "normal", "high"], index=1)
            t_message = st.text_area("Describe your issue")
            if st.form_submit_button("Submit Ticket", type="primary"):
                ok, msg = ticket_manager.create(current_user.phone, t_subject, t_category, t_message, t_priority)
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown("---")
        st.markdown("### My Tickets")
        my_tickets = ticket_manager.my_tickets(current_user.phone)
        if not my_tickets:
            st.info("You have no tickets yet.")
        else:
            status_colors = {"open": "var(--mms-danger)", "in_progress": "var(--mms-primary-deep)",
                             "resolved": "var(--mms-primary-deep)", "closed": "var(--mms-muted)"}
            for tk in my_tickets:
                with st.container():
                    st.markdown(f"""
                    <div style="border: 1px solid var(--mms-border); padding: 12px; border-radius: 8px; margin-bottom: 8px;">
                        <div style="font-weight: bold; color: var(--mms-text);">#{tk['id']} — {tk['subject']}</div>
                        <div style="color: var(--mms-muted); font-size: 0.85em;">{tk['category']} • {tk['priority']} • opened {tk['created_at'].replace('T', ' ')[:16]}</div>
                        <div style="color: var(--mms-text); margin: 6px 0;">{tk['message']}</div>
                        <div style="color: {status_colors[tk['status']]}; font-weight: bold; font-size: 0.85em;">STATUS: {tk['status'].upper()}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if tk["admin_reply"]:
                        st.info(f"Support reply ({tk['replied_at'].replace('T', ' ')[:16]}): {tk['admin_reply']}")

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

        st.markdown("---")
        st.markdown("### Security")
        col_sec1, col_sec2 = st.columns(2)
        with col_sec1:
            st.markdown("**Two-Factor Authentication**")
            st.caption("Require a one-time code at login and for high-value transactions.")
            tfa_on = st.toggle(
                "OTP two-factor authentication",
                value=bool(current_user.two_factor_enabled),
                key="tfa_toggle",
            )
            if tfa_on != bool(current_user.two_factor_enabled):
                success, msg = user_manager.set_two_factor(current_user.phone, tfa_on)
                if success:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
        with col_sec2:
            st.markdown("**Active Sessions**")
            sessions = session_manager.list_active(current_user.phone)
            st.caption(f"{len(sessions)} active session(s) on your account")
            for sess in sessions:
                is_current = sess['token'] == st.session_state.get('session_token')
                device = sess['user_agent'] or 'unknown device'
                label = f"{sess['provider']} • {device} • last seen {sess['last_seen'].replace('T', ' ')[:16]}"
                if is_current:
                    label += " (this device)"
                col_slbl, col_sbtn = st.columns([4, 1])
                with col_slbl:
                    st.write(label)
                with col_sbtn:
                    if not is_current and st.button("Revoke", key=f"revoke_{sess['token'][:8]}"):
                        session_manager.revoke(sess['token'])
                        st.success("Session revoked.")
                        time.sleep(1)
                        st.rerun()
            if len(sessions) > 1 and st.button("Log Out Everywhere Else", type="primary"):
                n = session_manager.revoke_all(current_user.phone, except_token=st.session_state.get('session_token'))
                st.success(f"Revoked {n} other session(s).")
                time.sleep(1)
                st.rerun()

        st.markdown("---")
        st.markdown("### Notification Channels")
        st.caption("Get SMS / email alerts for your transactions. (Console delivery in this demo.)")
        with st.form("notif_form"):
            n_channel = st.selectbox("Channel", ["sms", "email"])
            n_dest = st.text_input("Phone number / Email address")
            if st.form_submit_button("Add Channel"):
                ok, msg = notification_service.add_channel(current_user.phone, n_channel, n_dest)
                if ok:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
        channels = notification_service.list_channels(current_user.phone)
        if channels:
            for ch in channels:
                col_n1, col_n2, col_n3 = st.columns([3, 2, 1])
                with col_n1:
                    st.write(f"{ch['channel'].upper()}: {ch['destination']}")
                with col_n2:
                    enabled = st.toggle("Enabled", value=bool(ch['enabled']), key=f"notif_en_{ch['id']}")
                    if enabled != bool(ch['enabled']):
                        notification_service.set_channel_enabled(current_user.phone, ch['id'], enabled)
                        st.rerun()
                with col_n3:
                    if st.button("Remove", key=f"notif_rm_{ch['id']}"):
                        notification_service.remove_channel(current_user.phone, ch['id'])
                        st.rerun()
        else:
            st.info("No notification channels yet.")

        st.markdown("---")
        st.markdown("### Privacy & Data")
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown("**Export my data**")
            st.caption("Download everything the platform holds about you (JSON or CSV).")
            export_data = privacy_manager.export_user_data(current_user.phone)
            if export_data:
                import json as _json
                st.download_button("Download my data (JSON)",
                                   data=_json.dumps(export_data, indent=2, default=str),
                                   file_name=f"my_data_{current_user.phone}.json",
                                   mime="application/json", key="privacy_json")
                st.download_button("Download my data (CSV)",
                                   data=export_to_csv(export_data),
                                   file_name=f"my_data_{current_user.phone}.csv",
                                   mime="text/csv", key="privacy_csv")
        with col_p2:
            st.markdown("**Delete my account**")
            st.caption("Requires admin approval. Financial records are kept but pseudonymized.")
            my_reqs = privacy_manager.my_deletion_requests(current_user.phone)
            pending_req = next((r for r in my_reqs if r["status"] == "pending"), None)
            if pending_req:
                st.warning(f"Deletion request #{pending_req['id']} is pending admin review.")
                if st.button("Withdraw Request", key="privacy_withdraw"):
                    privacy_manager.cancel_deletion_request(current_user.phone, pending_req["id"])
                    st.rerun()
            else:
                with st.form("deletion_form"):
                    reason = st.text_area("Reason (optional)")
                    confirm_del = st.checkbox("I understand my account will be deleted after admin approval")
                    if st.form_submit_button("Request Account Deletion", type="primary"):
                        if not confirm_del:
                            st.error("Please confirm you understand.")
                        else:
                            ok, msg = privacy_manager.request_deletion(current_user.phone, reason)
                            if ok:
                                st.success(msg)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
            for r in my_reqs:
                if r["status"] != "pending":
                    st.caption(f"Request #{r['id']}: {r['status']}"
                                + (f" ({r['reviewed_at'][:10]})" if r["reviewed_at"] else ""))

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
            st.markdown('<div class="empty-state"><i class="fa-solid fa-receipt"></i><p>No transactions yet.</p></div>', unsafe_allow_html=True)
        else:
            # Spending over recent days (debits only)
            from collections import defaultdict
            daily_spend: defaultdict[str, float] = defaultdict(float)
            for t in history:
                is_debit = (t.sender_phone == current_user.phone and t.type in ("TRANSFER", "WITHDRAWAL", "BILL_PAYMENT", "SUBSCRIPTION"))
                if is_debit:
                    daily_spend[t.timestamp[:10]] += float(t.amount)
            if daily_spend:
                st.markdown(f"#### 📈 {TR('spending')}")
                st.bar_chart(dict(sorted(daily_spend.items())[-7:]))
            # Sort by timestamp descending
            history.sort(key=lambda x: x.timestamp, reverse=True)

            for t in history:
                # Determine icon/color
                if t.type == "TRANSFER":
                    if t.sender_phone == current_user.phone:
                         icon = "fa-solid fa-arrow-turn-up"
                         color = "var(--mms-danger)"
                         icon_bg = "var(--mms-danger-soft)"
                         badge = "DEBIT"
                         desc_text = f"To: {t.receiver_phone}"
                    else:
                         icon = "fa-solid fa-arrow-turn-down"
                         color = "var(--mms-primary-deep)"
                         icon_bg = "var(--mms-primary-soft)"
                         badge = "CREDIT"
                         desc_text = f"From: {t.sender_phone}"
                elif t.type == "DEPOSIT":
                    icon = "fa-solid fa-circle-plus"
                    color = "var(--mms-primary-deep)"
                    icon_bg = "var(--mms-primary-soft)"
                    badge = "CREDIT"
                    desc_text = "System Deposit"
                elif t.type == "WITHDRAWAL":
                    icon = "fa-solid fa-circle-minus"
                    color = "var(--mms-danger)"
                    icon_bg = "var(--mms-danger-soft)"
                    badge = "DEBIT"
                    desc_text = "System Withdrawal"
                elif t.type == "BILL_PAYMENT":
                    icon = "fa-solid fa-file-invoice-dollar"
                    color = "var(--mms-danger)"
                    icon_bg = "var(--mms-danger-soft)"
                    badge = "DEBIT"
                    desc_text = "Bill Payment"
                else:
                    icon = "fa-solid fa-list"
                    color = "var(--mms-muted)"
                    icon_bg = "var(--mms-surface-2)"
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
                        <div class="tx-icon" style="color: {color}; background-color: {icon_bg};">
                            <i class="{icon}"></i>
                        </div>
                        <div class="tx-details">
                            <div style="font-weight: 500; color: var(--mms-text);">{detail_text}</div>
                            <div style="font-size: 0.8rem; color: var(--mms-muted);">{t.timestamp.replace('T', ' ')[:16]}</div>
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
                    st.download_button(
                        label="Download Receipt (PDF)",
                        data=receipt_pdf(t, sender_name, receiver_name),
                        file_name=f"receipt_{t.id}.pdf",
                        mime="application/pdf",
                        key=f"dlpdf_{t.id}"
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
