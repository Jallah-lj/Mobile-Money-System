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
| `users.py` | Auth (bcrypt + lockout + OTP), KYC, user helpers |
| `database.py` | SQLite schema + idempotent migrations (auto-runs on startup) |
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
```

## Pricing — free for everyone

The platform is **free to use**: no subscription, no paywall. Everyone gets:

| Operation | Rate |
|---|---|
| Transfer | 0% |
| Withdrawal | 0.5% |
| Bill payment | $0.25 flat |
| Per-transaction limit | risk-tier scaled ($1k–$50k) × 10 |
