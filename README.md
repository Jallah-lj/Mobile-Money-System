# 📱 Mobile Money System

A production-grade mobile money platform built with Python. It ships with three
surfaces — a **Streamlit web app**, a **FastAPI REST API**, and a **CLI** — all
driven by the same core engine: SQLite persistence, a double-entry ledger,
bcrypt-hashed PINs, KYC, and AML monitoring. The platform is **free to use** — no subscription, no paywall.

---

## ✨ Features

### 💰 Core Wallet
- **Send / Request money** with a two-step verification review screen
- **Pay bills** (airtime, electricity, water, internet)
- **Load money** from a linked card & **withdraw** to cash
- **Inbox** with real-time notifications and per-transaction receipts (downloadable)
- **Transaction history** with spending analytics

### 💸 Pricing — free for everyone

The platform is **free to use**: there is no subscription and no paywall.
Everyone gets the same rates and limits:

| Item | Rate |
|---|---|
| P2P transfer fee | **0%** |
| Withdrawal fee | **0.5%** |
| Bill payment fee | **$0.25** flat |
| Per-transaction limit | risk-tier scaled ($1k–$50k) **× 10** |

### 🛡️ Security & Compliance
- **bcrypt** PIN hashing (with automatic legacy-hash upgrade on login)
- **Login lockout**: 5 failed attempts → 15-minute lockout
- **OTP 2FA** on web login (single-use, 5-minute expiry codes)
- **Append-only audit log** of every security-relevant event (logins, transfers,
  admin actions, KYC) — viewable in the admin panel and via the API
- **AML monitoring**: large-amount and velocity (rapid movement) flagging
- **KYC gating**: unverified accounts cannot transact
- **Risk tiers** (low / standard / high) with per-tier transaction limits
- **Idle session timeout** (15 minutes) in the web app
- **API key authentication** for the REST API (set `MMS_API_KEY`)
- API responses never expose PIN hashes or security answers

### 🌐 Internationalization & UX
- UI in **English, Français, Español, Swahili**
- **Dark mode** toggle
- Design system with tokens, light & dark themes (WCAG AA contrast, responsive)

### 🧑‍💼 Admin Panel
- System metrics (users, float, transactions, risk alerts)
- User management (KYC, suspend/reactivate, risk tier, PIN reset, impersonation)
- Transaction oversight, reversal console, manual balance adjustments
- **Audit log** viewer with filters and CSV export
- Revenue analytics with real CSV exports
- Security center (fraud rule configuration)

---

## 🚀 Quickstart

```bash
# 1. Install dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r mobile_money_system/requirements.txt

# 2a. Run the web app
streamlit run mobile_money_system/app.py
#     → http://localhost:8501   (default admin: 0000000000 / admin123)

# 2b. Run the REST API
MMS_API_KEY=change-me uvicorn mobile_money_system.api:app --reload
#     → http://localhost:8000/docs   (set MMS_API_KEY to enable auth)

# 2c. Run the CLI
python mobile_money_system/main.py
```

The database (`mobile_money.db`) is created and migrated automatically on first run.

### Promoting an admin
```bash
python set_admin.py <phone_number>
```

---

## 🧪 Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

27 tests cover the transaction core, compliance (KYC/AML), money requests,
and security hardening (lockout, OTP, audit trail, fresh-DB bootstrap).
CI runs the same suite on every push (`.github/workflows/tests.yml`).

---

## 🗂️ Project Structure

```
mobile_money_system/
  app.py            Streamlit web app (users + admin panel)
  api.py            FastAPI REST API (API-key auth, audit endpoints)
  main.py           CLI client
  audit.py          Append-only audit log
  transactions.py   Core financial operations (fees, limits, AML)
  users.py          User management, auth, lockout, KYC
  database.py       SQLite schema + idempotent migrations
  ledger.py         Double-entry bookkeeping (every batch sums to zero)
  models.py         Dataclasses: User, Transaction, LedgerEntry, AuditEntry
  i18n.py           Translations (en / fr / es / sw)
  styles.py         Design system (light & dark themes)
tests/              pytest suite (27 tests)
set_admin.py        Promote a user to admin (SQLite)
```

---

## ☁️ Deployment

The Azure Web App workflow (`.github/workflows/main_jallah-webapp-dev-cc.yml`)
builds and deploys on pushes to `main`.

---

## 📄 License

MIT
