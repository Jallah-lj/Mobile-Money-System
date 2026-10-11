# Mobile Money System — Package

Core package for the Mobile Money platform. See the [root README](../../README.md)
for the full feature overview (free pricing, security, quickstart).

## Modules

| Module | Responsibility |
|---|---|
| `app.py` | Streamlit web app — user dashboard + admin panel |
| `api.py` | FastAPI REST API — set `MMS_API_KEY` to enable key auth |
| `main.py` | CLI client |
| `audit.py` | Append-only audit log of security-relevant events |
| `transactions.py` | Financial operations: fees, limits, AML |
| `users.py` | Auth (bcrypt + lockout + OTP), KYC, user helpers, 2FA toggle |
| `sessions.py` | Server-side login session management (revoke, log-out-everywhere) |
| `beneficiaries.py` | Saved recipients with nicknames + recent recipients |
| `scheduled.py` | Scheduled & recurring payments (standing orders) |
| `analytics.py` | Personal analytics & monthly account statements |
| `pdfdoc.py` | Dependency-free PDF writer (receipts, statements) |
| `webhooks.py` | Signed outbound webhooks (HMAC-SHA256 + delivery log) |
| `notifications.py` | SMS/email notifications (console + SMTP providers) |
| `tickets.py` | Support ticketing (user tickets + admin queue) |
| `privacy.py` | GDPR-style data export + account deletion (pseudonymized) |
| `billers.py` | Registered billers for the Pay Bills page |
| `config.py` | Operator settings (fees, AML thresholds, retention) in SQLite |
| `events.py` | Async event dispatcher (webhooks/notifications off the payment path) |
| `backup.py` | Database snapshots + restore (SQLite online backup API) |
| `reconcile.py` | Ledger reconciliation (balances, double-entry invariant) |
| `retention.py` | Configurable data-retention pruning |
| `logging_config.py` | Structured JSON-lines operational logging |
| `scheduler_worker.py` | Standalone worker: due payments + daily maintenance |
| `database.py` | SQLite schema + idempotent migrations (WAL, indexes, auto-runs) |
| `ledger.py` | Double-entry bookkeeping — every posted batch sums to zero |
| `models.py` | `User`, `Transaction`, `LedgerEntry`, `AuditEntry` dataclasses |
| `i18n.py` | Translations: English, Français, Español, Swahili |
| `styles.py` | Design system with light & dark themes |

## Run

```bash
# Web app
streamlit run mobile_money_system/app.py

# REST API (from the repo root)
MMS_API_KEY=change-me uvicorn mobile_money_system.api:app --reload

# CLI
python mobile_money_system/main.py

# Standalone scheduler worker (fires due standing orders without the app)
python -m mobile_money_system.scheduler_worker
```

## Pricing — free for everyone

The platform is **free to use**: no subscription, no paywall. Everyone gets:

| Operation | Rate |
|---|---|
| Transfer | 0% |
| Withdrawal | 0.5% |
| Bill payment | $0.25 flat |
| Per-transaction limit | risk-tier scaled ($1k–$50k) × 10 |
