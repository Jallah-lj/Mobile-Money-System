# Mobile Money System — Package

Core package for the Mobile Money platform. See the [root README](../../README.md)
for the full feature overview (Premium membership, security, quickstart).

## Modules

| Module | Responsibility |
|---|---|
| `app.py` | Streamlit web app — user dashboard + admin panel |
| `api.py` | FastAPI REST API — set `MMS_API_KEY` to enable key auth |
| `main.py` | CLI client — includes the Premium membership menu |
| `premium.py` | Premium tier engine (perks, fee schedule, limits, loyalty points) |
| `audit.py` | Append-only audit log of security-relevant events |
| `transactions.py` | Financial operations: fees, limits, AML, subscriptions |
| `users.py` | Auth (bcrypt + lockout + OTP), KYC, user & premium helpers |
| `database.py` | SQLite schema + idempotent migrations (auto-runs on startup) |
| `ledger.py` | Double-entry bookkeeping — every posted batch sums to zero |
| `models.py` | `User`, `Transaction`, `LedgerEntry`, `AuditEntry` dataclasses |
| `i18n.py` | Translations: English, Français, Español, Swahili |
| `styles.py` | Premium design system with light & dark themes |

## Run

```bash
# Web app
streamlit run mobile_money_system/app.py

# REST API (from the repo root)
MMS_API_KEY=change-me uvicorn mobile_money_system.api:app --reload

# CLI
python mobile_money_system/main.py
```

## Fee schedule

| Operation | Free tier | Premium |
|---|---|---|
| Transfer | 1% | 0% |
| Withdrawal | 1% | 0.5% |
| Bill payment | $0.50 flat | $0.25 flat |
| Per-transaction limit | risk-tier scaled ($1k–$50k) | 10× |

Premium subscription: **$4.99 / 30 days** (stacks on renewal; 500 loyalty
points = 1 free month; KYC required).
