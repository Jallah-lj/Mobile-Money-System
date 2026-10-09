# 📱 Mobile Money System

A production-grade mobile money platform built with Python. It ships with three
surfaces — a **Streamlit web app**, a **FastAPI REST API**, and a **CLI** — all
driven by the same core engine: SQLite persistence, a double-entry ledger,
bcrypt-hashed PINs, KYC, AML monitoring, and a **Premium membership tier**.

---

## ✨ Features

### 💰 Core Wallet
- **Send / Request money** with a two-step verification review screen
- **Pay bills** (airtime, electricity, water, internet)
- **Load money** from a linked card & **withdraw** to cash
- **Inbox** with real-time notifications and per-transaction receipts (downloadable)
- **Transaction history** with spending analytics

### ⭐ Premium Membership — $4.99 / 30 days

| Perk | Free tier | Premium |
|---|---|---|
| P2P transfer fee | 1% | **0%** |
| Withdrawal fee | 1% | **0.5%** |
| Bill payment fee | $0.50 | **$0.25** |
| Per-transaction limit | $5,000 (risk-tier scaled) | **10×** |
| Loyalty points | — | **1 pt per $10 spent** |
| Points redemption | — | **500 pts = 1 free month** |

Subscriptions stack on renewal, are charged through the double-entry ledger
(`SYSTEM_REVENUE`), and can be redeemed with loyalty points. KYC verification is
required to subscribe.

### 🛡️ Security & Compliance
- **bcrypt** PIN hashing (with automatic legacy-hash upgrade on login)
- **Login lockout**: 5 failed attempts → 15-minute lockout
- **OTP 2FA** on web login (single-use, 5-minute expiry codes)
- **Append-only audit log** of every security-relevant event (logins, transfers,
  admin actions, KYC, subscriptions) — viewable in the admin panel and via the API
- **AML monitoring**: large-amount and velocity (rapid movement) flagging
- **KYC gating**: unverified accounts cannot transact
- **Risk tiers** (low / standard / high) with per-tier transaction limits
- **Idle session timeout** (15 minutes) in the web app
- **API key authentication** for the REST API (set `MMS_API_KEY`)
- API responses never expose PIN hashes or security answers

### 🌐 Internationalization & UX
- UI in **English, Français, Español, Swahili**
- **Dark mode** toggle
- Premium design system (design tokens, gold Premium branding, responsive)

### 🧑‍💼 Admin Panel
- System metrics (users, float, transactions, **Premium subscribers**, risk alerts)
- User management (KYC, suspend/reactivate, risk tier, PIN reset, impersonation)
- Transaction oversight, reversal console, manual balance adjustments
- **Audit log** viewer with filters and CSV export
- Revenue analytics incl. **subscription revenue**, real CSV exports
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

44 tests cover the transaction core, compliance (KYC/AML), money requests,
the Premium tier (subscription, perks, limits, loyalty points, redemption),
and security hardening (lockout, OTP, audit trail, fresh-DB bootstrap).
CI runs the same suite on every push (`.github/workflows/tests.yml`).

---

## 🗂️ Project Structure

```
mobile_money_system/
  app.py            Streamlit web app (users + admin panel)
  api.py            FastAPI REST API (API-key auth, premium & audit endpoints)
  main.py           CLI client (incl. Premium membership menu)
  premium.py        Premium tier engine: perks, fee schedule, limits, points
  audit.py          Append-only audit log
  transactions.py   Core financial operations (fees, limits, AML, subscriptions)
  users.py          User management, auth, lockout, KYC, premium helpers
  database.py       SQLite schema + idempotent migrations
  ledger.py         Double-entry bookkeeping (every batch sums to zero)
  models.py         Dataclasses: User, Transaction, LedgerEntry, AuditEntry
  i18n.py           Translations (en / fr / es / sw)
  styles.py         Premium design system (light & dark themes)
tests/              pytest suite (44 tests)
set_admin.py        Promote a user to admin (SQLite)
```

---

## ☁️ Deployment

The Azure Web App workflow (`.github/workflows/main_jallah-webapp-dev-cc.yml`)
builds and deploys on pushes to `main`.

---

## 📄 License

MIT
