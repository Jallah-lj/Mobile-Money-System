# 📱 Mobile Money System

A production-grade mobile money platform built with Python. It ships with three
surfaces — a **Streamlit web app**, a **FastAPI REST API**, and a **CLI** — all
driven by the same core engine: SQLite persistence, a double-entry ledger,
bcrypt-hashed PINs, KYC, and AML monitoring. The platform is **free to use** — no subscription, no paywall.

---

## ✨ Features

### 💰 Core Wallet
- **Send / Request money** with a two-step verification review screen
- **Saved beneficiaries** (nicknames + recent recipients) — pay anyone in one tap
- **Scheduled & recurring payments** — one-off future payments and standing
  orders (daily / weekly / monthly) for transfers and bills, executed
  automatically with full run history
- **Pay bills** (airtime, electricity, water, internet)
- **Load money** from a linked card & **withdraw** to cash
- **Inbox** with real-time notifications
- **Transaction history** with **receipts downloadable as text or PDF**

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
- **OTP 2FA** on web login (single-use, 5-minute expiry codes), user-toggleable
  in Settings
- **Step-up authentication**: debits above $1,000 require a fresh OTP even
  when logged in
- **Server-side session management**: active-sessions list, per-device revoke,
  and "Log Out Everywhere Else" — a revoked session ends the login immediately
- **API rate limiting**: per-IP sliding-window limits (general, login,
  register) with HTTP 429 + Retry-After
- **Append-only audit log** of every security-relevant event (logins, transfers,
  admin actions, KYC) — viewable in the admin panel and via the API
- **AML monitoring**: large-amount and velocity (rapid movement) flagging
- **KYC gating**: unverified accounts cannot transact
- **Risk tiers** (low / standard / high) with per-tier transaction limits
- **Idle session timeout** (15 minutes) in the web app
- **API key authentication** for the REST API (set `MMS_API_KEY`)
- API responses never expose PIN hashes or security answers

### 💼 Personal Finance
- **Insights dashboard**: monthly budget with over-budget alerts, 6-month
  income-vs-spending trend, spending by category, top recipients
- **Monthly account statements**: opening/closing balances, money in/out,
  fees, full transaction list — downloadable as **CSV or PDF**

### 🔌 Integrations
- **Signed webhooks** (admin-managed): JSON push of every transaction event
  with HMAC-SHA256 signature headers, retry with backoff, and a delivery log
- **SMS / email notifications**: per-user channels in Settings; both parties
  are alerted on transfers/deposits/withdrawals/bills/requests (console
  provider by default, real SMTP via `MMS_SMTP_*` env vars)
- **Support ticketing**: users open tickets and see replies; admins work a
  filtered queue with reply + status flow

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
- **Support ticket queue** (filters, reply, status flow)
- **Webhook management** (endpoints, events, delivery log)
- **Fee & AML rule configuration** (operator pricing, fraud thresholds)
- **Registered billers** management (users pick them on Pay Bills)
- **Backups** (create / download / restore, with auto-backup)
- **Ledger reconciliation** (balances vs double-entry ledger, money conservation)
- **Data retention** (configurable pruning of old security/ops rows)

### ⚙️ Reliability & Operations
- **Atomic money movement** — every balance change is one SQLite write
  transaction (BEGIN IMMEDIATE): no double-spend under concurrency, no
  partial state on failure
- **SQLite WAL** + busy timeout + indexes on hot query paths
- **Durable security state** — OTPs, login lockouts and API rate limits are
  database-backed: they survive restarts and work across workers
- **Async event dispatch** — webhooks/notifications deliver on a background
  thread; a slow integration never delays a payment
- **Background scheduler** — standing orders fire on a timer (in-app thread,
  or the docker-compose `scheduler` worker) even when the app is idle
- **API idempotency** — `Idempotency-Key` on transfers makes retries safe
- **Structured logging** — JSON-lines operational log (`logs/mms.log`)
- **Detailed `/health`** — database status, journal mode, counts, uptime

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

151 tests cover the transaction core, compliance (KYC/AML), money requests,
security hardening (lockout, OTP, audit trail, sessions, 2FA, API rate
limiting), atomicity under concurrency, durable security state, async event
dispatch, the background scheduler, beneficiaries, scheduled payments,
analytics & statements, privacy data controls, backups, reconciliation,
retention, idempotency, and the integrations (webhook signatures & delivery,
notifications, tickets).
CI runs the same suite on every push (`.github/workflows/tests.yml`) plus
ruff + mypy (`.github/workflows/lint.yml`).

---

## 🗂️ Project Structure

```
mobile_money_system/
  app.py            Streamlit web app (users + admin panel)
  api.py            FastAPI REST API (API-key auth, audit endpoints)
  main.py           CLI client
  audit.py          Append-only audit log
  transactions.py   Core financial operations (fees, limits, AML)
  users.py          User management, auth, lockout, KYC, 2FA toggle
  sessions.py       Server-side login session management
  beneficiaries.py  Saved recipients (nicknames, usage tracking)
  scheduled.py      Scheduled & recurring payments (standing orders)
  analytics.py      Personal analytics & monthly statements
  pdfdoc.py         Dependency-free PDF writer (receipts, statements)
  webhooks.py       Signed outbound webhooks (HMAC-SHA256, delivery log)
  notifications.py  SMS/email notification service (pluggable providers)
  tickets.py        Support ticketing (user tickets + admin queue)
  database.py       SQLite schema + idempotent migrations
  ledger.py         Double-entry bookkeeping (every batch sums to zero)
  models.py         Dataclasses: User, Transaction, LedgerEntry, AuditEntry
  i18n.py           Translations (en / fr / es / sw)
  styles.py         Design system (light & dark themes)
tests/              pytest suite (97 tests)
set_admin.py        Promote a user to admin (SQLite)
```

---

## ☁️ Deployment

Docker (recommended): `docker compose up --build` runs the web app, the REST
API, and a scheduler worker sharing one database volume — see
[DEPLOYMENT.md](DEPLOYMENT.md) for TLS, `MMS_API_KEY`, backups, and the
production checklist.

The Azure Web App workflow (`.github/workflows/main_jallah-webapp-dev-cc.yml`)
builds and deploys on pushes to `main`.

---

## 📄 License

MIT
