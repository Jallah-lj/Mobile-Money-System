# Mobile Money — Flutter App

The mobile client for the Mobile Money platform. It talks to the **REST API**
(`mobile_money_system/api.py`) — the same backend the Streamlit webapp and CLI
use — so balances, transfers, bills, and history stay in sync everywhere.

## Screens (scaffold)

- **Login** — phone + PIN, with the 2FA OTP stage (2FA is on by default)
- **Register** — phone, name, PIN, security question/answer
- **Home** — balance, KYC status, quick actions, recent activity
- **Send money** — amount, recipient (pick from saved beneficiaries / recent
  recipients), optional "save as beneficiary"; every send carries a fresh
  `Idempotency-Key` so retries are safe
- **Pay bills** — biller catalog picker + amount
- **History** — full transaction list with direction and status

The `ApiClient` (`lib/api_client.dart`) wraps **all** app endpoints
(`/auth/*`, `/me/*`, `/billers`), so the remaining screens (scheduled
payments, support tickets, requests, KYC, data export) are thin additions.

## Requirements

- Flutter SDK 3.22+ (Dart 3.4+) — [install.flutter.dev](https://docs.flutter.dev/get-started/install)
- The REST API running and reachable (see below)
- An Android emulator/device (Android Studio) or an iOS simulator (Xcode, macOS)

> **Note:** this app cannot be built or run inside the Arena sandbox (no
> Flutter SDK, no Android/iOS toolchain). Clone the repo on your own machine
> and run it there.

## 1. Run the API

From the repo root:

```bash
# Development (open mode — do not use for production without MMS_API_KEY)
uvicorn mobile_money_system.api:app --host 0.0.0.0 --port 8000

# Or with Docker:  docker compose up api
```

Interactive API docs: http://localhost:8000/docs

## 2. Run the app

```bash
cd mobile_app
flutter pub get

# Android emulator (10.0.2.2 = the host machine running the API):
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

# iOS simulator (localhost works):
flutter run --dart-define=API_BASE_URL=http://localhost:8000

# Real phone: use your machine's LAN IP, and make sure the API binds 0.0.0.0
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
```

The default `API_BASE_URL` is `http://10.0.2.2:8000` (Android emulator → host).

## 3. Preview the app — three ways

**A. On your machine (emulator, simulator, or phone)** — section 2 above.

**B. In a browser — no emulator needed (Flutter web target):**

```bash
# API on localhost (CORS from localhost is allowed by default):
flutter run -d chrome --web-port 8080 --dart-define=API_BASE_URL=http://localhost:8000
```

This opens the app UI in Chrome. The API allows CORS from `localhost` /
`127.0.0.1` on any port by default; for a deployed web build set
`MMS_CORS_ORIGINS=https://your-app.example.com` on the API server.

**C. No setup at all — CI-built debug APK:**

The repo ships a ready-made workflow at `.github/workflows/mobile-apk.yml`
(see "Adding the CI workflow" below). Once added, every push that touches
`mobile_app/` builds a **debug APK** you can download from the GitHub Actions
tab (*Artifacts*) and install on any Android phone (enable "Install unknown
apps"). Rebuild with your API URL for a phone build:

```bash
flutter build apk --debug --dart-define=API_BASE_URL=https://api.example.com
```

## 4. Build a release binary

```bash
flutter build apk            # Android
flutter build ios            # iOS (macOS + Xcode)
flutter build appbundle      # Google Play
```

## Demo accounts

- System Admin: `0000000000` / PIN `admin123`
- Demo user: `+231776462520` / PIN `1234` (KYC verified, funded)

Both have 2FA enabled by default — the login screen will ask for the SMS code
(in development the code is printed to the API server console by the console
SMS provider).

## Adding the CI workflow

The sandbox's GitHub connection cannot push files under `.github/workflows/`
(lacking the `workflows` permission), so `mobile-apk.yml` is provided
untracked. Add it yourself in 30 seconds:

1. On GitHub, open your repo → `.github/workflows/` → **Add file** → **Create new file**
2. Name it `mobile-apk.yml` and paste the contents of the local
   `.github/workflows/mobile-apk.yml`
3. Commit — the workflow runs on pushes that touch `mobile_app/`

## Project layout

```
lib/
  main.dart               app entry + session bootstrap
  api_client.dart         typed wrapper for every REST endpoint
  screens/
    login_screen.dart     phone+PIN, 2FA OTP stage
    register_screen.dart  self-registration
    home_screen.dart      balance, quick actions, recent activity
    send_screen.dart      transfers + beneficiary picker
    pay_bills_screen.dart biller catalog + payment
    history_screen.dart   full transaction history
```
