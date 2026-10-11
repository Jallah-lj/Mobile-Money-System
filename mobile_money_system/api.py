"""FastAPI REST API for the Mobile Money System.

Security model:
  * If the MMS_API_KEY environment variable is set, every endpoint (except
    /health) requires an `X-API-Key` header matching it.
  * If it is not set, the API runs in open "development mode" and prints a
    warning at startup. Never deploy without setting a key.
  * User responses never expose PIN hashes or security answers.
  * The mobile app authenticates per user with Bearer session tokens
    (POST /auth/login); the /me/* endpoints identify the user from the token.
"""

import contextlib
import json
import os
import sqlite3
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

if __package__:
    from .audit import get_audit_logs
    from .beneficiaries import BeneficiaryManager
    from .billers import CATEGORIES, BillerManager
    from .database import get_db, write_transaction
    from .logging_config import setup_logging
    from .models import utcnow
    from .notifications import NotificationService
    from .privacy import PrivacyManager
    from .scheduled import ScheduledPaymentManager
    from .sessions import SessionManager
    from .tickets import TicketManager
    from .transactions import TransactionManager
    from .users import UserManager
else:
    from audit import get_audit_logs  # type: ignore[no-redef]
    from beneficiaries import BeneficiaryManager  # type: ignore[no-redef]
    from billers import CATEGORIES, BillerManager  # type: ignore[no-redef]
    from database import get_db, write_transaction  # type: ignore[no-redef]
    from logging_config import setup_logging  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]
    from notifications import NotificationService  # type: ignore[no-redef]
    from privacy import PrivacyManager  # type: ignore[no-redef]
    from scheduled import ScheduledPaymentManager  # type: ignore[no-redef]
    from sessions import SessionManager  # type: ignore[no-redef]
    from tickets import TicketManager  # type: ignore[no-redef]
    from transactions import TransactionManager  # type: ignore[no-redef]
    from users import UserManager  # type: ignore[no-redef]

API_KEY_NAME = "X-API-Key"
API_KEY_ENV_VAR = "MMS_API_KEY"
EXPECTED_API_KEY = os.environ.get(API_KEY_ENV_VAR)


# --- Rate limiting -----------------------------------------------------------
# Sliding-window limiter backed by SQLite. Per-endpoint-class limits protect
# the API from brute-force and abuse without any external dependencies, and
# because hits live in the database they are enforced across server
# processes/workers and survive restarts. (Account-level lockout for logins
# is additionally enforced by UserManager.)
class RateLimiter:
    """Sliding-window rate limiter: at most `max_requests` per `window_seconds`."""

    def __init__(self, max_requests: int, window_seconds: float, key_prefix: str = ""):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    def _scoped(self, key: str) -> str:
        return f"{self.key_prefix}{key}" if self.key_prefix else key

    def allow(self, key: str) -> tuple[bool, int]:
        """Record a hit for `key`. Returns (allowed, retry_after_seconds).

        One short write transaction per call: prune expired hits, count the
        hits inside the window, insert the new hit. Serialized by SQLite's
        write lock, so concurrent workers cannot overshoot the limit.
        """
        key = self._scoped(key)
        now = time.time()
        window_start = now - self.window_seconds
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM rate_limit_hits WHERE key = ? AND at < ?",
                            (key, window_start))
                row = cur.execute(
                    "SELECT COUNT(*) AS n, MIN(at) AS oldest FROM rate_limit_hits WHERE key = ?",
                    (key,)).fetchone()
                if row["n"] >= self.max_requests:
                    retry_after = int(self.window_seconds - (now - row["oldest"])) + 1
                    return False, max(retry_after, 1)
                cur.execute("INSERT INTO rate_limit_hits (key, at) VALUES (?, ?)", (key, now))
                return True, 0
        except sqlite3.Error:
            # Fail open if the database is unavailable — availability first.
            return True, 0

    def reset(self, key: str) -> None:
        """Clear all recorded hits for `key`."""
        with get_db() as conn:
            conn.execute("DELETE FROM rate_limit_hits WHERE key = ?", (self._scoped(key),))
            conn.commit()


# Per-IP limits per endpoint class
GENERAL_LIMIT = (120, 60)    # 120 requests/minute per client IP
LOGIN_LIMIT = (10, 60)       # 10 login attempts/minute per client IP
REGISTER_LIMIT = (20, 60)    # 20 registrations/minute per client IP

_general_limiter = RateLimiter(*GENERAL_LIMIT)
_login_limiter = RateLimiter(*LOGIN_LIMIT)
_register_limiter = RateLimiter(*REGISTER_LIMIT)

RATE_LIMIT_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

_START_TIME = time.time()

setup_logging()


# --- Idempotency -------------------------------------------------------------
# Clients can send an `Idempotency-Key` header on POST /transactions/transfer.
# A retried request with the same key replays the stored response instead of
# executing the transfer twice — safe retries over flaky networks.
def _idempotent_replay(key: str, endpoint: str):
    """Return the stored response for a previously-seen key, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status_code, response FROM idempotency_keys WHERE key = ? AND endpoint = ?",
            (key, endpoint)).fetchone()
    if not row:
        return None
    return JSONResponse(status_code=row["status_code"],
                        content=json.loads(row["response"]),
                        headers={"X-Idempotent-Replay": "true"})


def _store_idempotent(key: str, endpoint: str, status_code: int, body: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys (key, endpoint, status_code, response, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (key, endpoint, status_code, json.dumps(body), utcnow().isoformat()))
        conn.commit()


app = FastAPI(
    title="Mobile Money System API",
    description="REST API for wallet operations and compliance audit trails.",
    version="2.0.0",
)

# --- CORS ---------------------------------------------------------------------
# Native app targets (Android/iOS) are unaffected by CORS; this exists so the
# Flutter app can also be previewed in a browser (`flutter run -d chrome`).
# Default: local dev servers on any port. For a deployed web build, set
# MMS_CORS_ORIGINS="https://app.example.com,https://www.example.com".
_CORS_ENV = os.environ.get("MMS_CORS_ORIGINS", "")
if _CORS_ENV:
    _cors_origins = [o.strip() for o in _CORS_ENV.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Singletons for the app lifecycle
user_mgr = UserManager()
txn_mgr = TransactionManager(user_mgr)
privacy_mgr = PrivacyManager()
session_mgr = SessionManager()
beneficiary_mgr = BeneficiaryManager(user_mgr)
biller_mgr = BillerManager()
scheduled_mgr = ScheduledPaymentManager(user_mgr, txn_mgr)
ticket_mgr = TicketManager()
notification_service = NotificationService(user_mgr)

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def verify_api_key(api_key: str | None = Security(api_key_header)):
    """Enforce API key auth when MMS_API_KEY is configured."""
    if EXPECTED_API_KEY is None:
        return  # Development mode (a warning is printed at startup)
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


AUTH = Security(verify_api_key)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Reject clients that exceed the per-IP rate limits with HTTP 429."""
    path = request.url.path
    if path in RATE_LIMIT_EXEMPT_PATHS or not path.startswith("/"):
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"

    allowed, retry_after = _general_limiter.allow(f"general:{client_ip}")
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
            headers={"Retry-After": str(retry_after)},
        )

    endpoint_limiter = None
    if path in ("/users/login", "/auth/login", "/auth/verify-otp"):
        endpoint_limiter = _login_limiter
    elif path in ("/users/register", "/auth/register"):
        endpoint_limiter = _register_limiter
    if endpoint_limiter is not None:
        allowed, retry_after = endpoint_limiter.allow(f"{path}:{client_ip}")
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many attempts. Try again later."},
                headers={"Retry-After": str(retry_after)},
            )

    return await call_next(request)

if EXPECTED_API_KEY is None:
    print("WARNING: MMS_API_KEY is not set — the API is running in open development mode.")


class RegisterRequest(BaseModel):
    phone: str
    name: str
    pin: str
    sec_q: str
    sec_a: str
    currency: str = "USD"

class KYCRequest(BaseModel):
    phone: str
    id_type: str
    id_number: str

class LoginRequest(BaseModel):
    phone: str
    pin: str

class TransactionRequest(BaseModel):
    phone: str
    amount: float
    description: str = ""

class TransferRequest(BaseModel):
    sender_phone: str
    receiver_phone: str
    amount: float
    description: str = ""

class BillRequest(BaseModel):
    phone: str
    amount: float
    biller_name: str
    biller_id: str
    description: str = "Bill Payment"


@app.get("/health", tags=["system"])
def health():
    """Liveness + readiness probe — always unauthenticated."""
    info = {
        "status": "ok",
        "auth_required": EXPECTED_API_KEY is not None,
        "version": "2.1.0",
        "uptime_seconds": int(time.time() - _START_TIME),
    }
    try:
        with get_db() as conn:
            info["database"] = "ok"
            info["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            info["users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            info["transactions"] = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    except sqlite3.Error as e:
        info["database"] = f"error: {e}"
        info["status"] = "degraded"
    return info


@app.post("/users/register", dependencies=[AUTH], tags=["users"])
def register(req: RegisterRequest):
    success, msg = user_mgr.register(req.phone, req.name, req.pin, req.sec_q, req.sec_a, req.currency)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/users/login", dependencies=[AUTH], tags=["users"])
def login(req: LoginRequest):
    user = user_mgr.login(req.phone, req.pin)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials or account locked")
    return user.to_public_dict()


@app.post("/users/{phone}/kyc", dependencies=[AUTH], tags=["users"])
def submit_kyc(phone: str, req: KYCRequest):
    if phone != req.phone:
        raise HTTPException(status_code=400, detail="Phone mismatch")
    success, msg = user_mgr.submit_kyc(req.phone, req.id_type, req.id_number)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.get("/users/{phone}", dependencies=[AUTH], tags=["users"])
def get_user(phone: str):
    user = user_mgr.get_user(phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_public_dict()


@app.post("/transactions/deposit", dependencies=[AUTH], tags=["transactions"])
def deposit(req: TransactionRequest):
    success, msg = txn_mgr.deposit(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/transactions/withdraw", dependencies=[AUTH], tags=["transactions"])
def withdraw(req: TransactionRequest):
    success, msg = txn_mgr.withdraw(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/transactions/transfer", dependencies=[AUTH], tags=["transactions"])
def transfer(req: TransferRequest, request: Request):
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        replay = _idempotent_replay(idempotency_key, "transfer")
        if replay is not None:
            return replay
    success, msg, txn = txn_mgr.transfer_with_ref(
        req.sender_phone, req.receiver_phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    body = {"message": msg, "reference": txn.id if txn else None}
    if idempotency_key:
        _store_idempotent(idempotency_key, "transfer", 200, body)
    return body


@app.post("/transactions/pay-bill", dependencies=[AUTH], tags=["transactions"])
def pay_bill(req: BillRequest):
    success, msg = txn_mgr.pay_bill(req.phone, req.amount, req.biller_name, req.biller_id, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.get("/transactions/{phone}/history", dependencies=[AUTH], tags=["transactions"])
def get_history(phone: str):
    txns = txn_mgr.get_history(phone)
    return [t.to_dict() for t in txns]


@app.get("/users/{phone}/data-export", dependencies=[AUTH], tags=["users"])
def export_user_data(phone: str):
    """Privacy data export: everything the platform holds about the user."""
    data = privacy_mgr.export_user_data(phone)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return data


@app.get("/admin/audit", dependencies=[AUTH], tags=["admin"])
def audit_log(limit: int = Query(200, ge=1, le=1000),
              actor: str | None = Query(None),
              action: str | None = Query(None)):
    """Compliance audit trail, newest first, with optional filters."""
    return [e.to_dict() for e in get_audit_logs(limit=limit, actor_phone=actor, action=action)]

# ============================================================================
# Mobile app (consumer) API
# ============================================================================
# The Flutter app authenticates per user with a Bearer token. Tokens are rows
# in the existing `sessions` table (provider="mobile"): durable across
# restarts, revocable per device and via "log out everywhere", and issued only
# after PIN verification — plus an SMS OTP when the account has 2FA enabled.
# App endpoints identify the user from the token, never from the request body,
# and work with or without MMS_API_KEY (which guards the server-to-server
# endpoints above).

bearer_scheme = HTTPBearer(auto_error=False)
bearer_security = Security(bearer_scheme)  # module-level singleton (ruff B008)
_SESSION_TOUCH_SECONDS = 60


def verify_app_token(
    credentials: HTTPAuthorizationCredentials | None = bearer_security,
) -> str:
    """Authenticate a mobile-app request by its Bearer session token.

    Returns the authenticated user's phone; raises 401 for missing, unknown,
    or revoked tokens.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    sess = session_mgr.get_session(token)
    if not sess or not sess.get("active"):
        raise HTTPException(status_code=401, detail="Invalid or expired session",
                            headers={"WWW-Authenticate": "Bearer"})
    # Throttled activity tracking: at most one last_seen write per minute.
    try:
        last_seen = datetime.fromisoformat(str(sess["last_seen"]))
        if (utcnow() - last_seen).total_seconds() >= _SESSION_TOUCH_SECONDS:
            session_mgr.touch(token)
    except (ValueError, TypeError):
        session_mgr.touch(token)
    return str(sess["phone"])


APP_AUTH = Security(verify_app_token)


def _issue_app_session(phone: str, request: Request) -> dict:
    """Create a mobile session for a verified user and return the token payload."""
    user = user_mgr.get_user(phone) or user_mgr.get_user(user_mgr.format_phone(phone))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    token = session_mgr.create_session(
        user.phone, provider="mobile",
        user_agent=request.headers.get("user-agent", ""),
        ip=request.client.host if request.client else "")
    return {"access_token": token, "token_type": "bearer", "user": user.to_public_dict()}


class AppRegisterRequest(BaseModel):
    phone: str
    name: str
    pin: str
    sec_q: str
    sec_a: str
    currency: str = "USD"


class AppLoginRequest(BaseModel):
    phone: str
    pin: str


class AppOtpVerifyRequest(BaseModel):
    phone: str
    code: str


@app.post("/auth/register", tags=["auth"])
def app_register(req: AppRegisterRequest):
    """Self-registration from the mobile app (rate-limited; no API key needed)."""
    ok, msg = user_mgr.register(req.phone, req.name, req.pin, req.sec_q, req.sec_a, req.currency)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/auth/login", tags=["auth"])
def app_login(req: AppLoginRequest, request: Request):
    """PIN login. Returns a Bearer token — or requires_otp when 2FA is on."""
    user = user_mgr.login(req.phone, req.pin)  # account lockout enforced inside
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials or account locked")
    if user.two_factor_enabled:
        code = user_mgr.generate_otp(user.phone)
        with contextlib.suppress(Exception):
            # Delivery is best-effort; the issued code remains valid.
            notification_service.sms_provider.send_sms(
                user.phone, f"Your Mobile Money security code is {code}. It expires in 5 minutes.")
        return {"requires_otp": True, "message": "Security code sent."}
    return _issue_app_session(user.phone, request)


@app.post("/auth/verify-otp", tags=["auth"])
def app_verify_otp(req: AppOtpVerifyRequest, request: Request):
    """Complete a 2FA login: verify the SMS code and receive a Bearer token."""
    verified = user_mgr.verify_otp(req.phone, req.code) \
        or user_mgr.verify_otp(user_mgr.format_phone(req.phone), req.code)
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    return _issue_app_session(req.phone, request)


@app.post("/auth/logout", tags=["auth"])
def app_logout(credentials: HTTPAuthorizationCredentials | None = bearer_security):
    """Revoke the current app session token."""
    if credentials is not None:
        session_mgr.revoke(credentials.credentials)
    return {"message": "Logged out"}


@app.get("/auth/me", tags=["auth"])
def app_me(phone: str = APP_AUTH):
    """Current user profile + balance (fresh from the database)."""
    user = user_mgr.get_user(phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_public_dict()


# --- Wallet -------------------------------------------------------------------

class AppTransferRequest(BaseModel):
    receiver_phone: str
    amount: float
    description: str = ""


@app.post("/me/transfer", tags=["app"])
def app_transfer(req: AppTransferRequest, request: Request, phone: str = APP_AUTH):
    """Send money to another user. Send an Idempotency-Key header for safe retries."""
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        replay = _idempotent_replay(idempotency_key, "me/transfer")
        if replay is not None:
            return replay
    ok, msg, txn = txn_mgr.transfer_with_ref(phone, req.receiver_phone, req.amount, req.description)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    body = {"message": msg, "reference": txn.id if txn else None,
            "transaction": txn.to_dict() if txn else None}
    if idempotency_key:
        _store_idempotent(idempotency_key, "me/transfer", 200, body)
    return body


class AppRequestMoneyRequest(BaseModel):
    payer_phone: str
    amount: float
    description: str = "Money Request"


@app.post("/me/request", tags=["app"])
def app_request_money(req: AppRequestMoneyRequest, phone: str = APP_AUTH):
    """Request money from another user (no money moves until they pay)."""
    ok, msg = txn_mgr.request_money(phone, req.payer_phone, req.amount, req.description)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.get("/me/requests", tags=["app"])
def app_list_requests(phone: str = APP_AUTH):
    """Money requests involving the user, newest first, with direction."""
    requests = []
    for t in txn_mgr.get_history(phone):
        if t.type != "REQUEST":
            continue
        entry = t.to_dict()
        entry["direction"] = "incoming" if t.sender_phone == phone else "outgoing"
        requests.append(entry)
    return {"requests": requests}


def _process_request_for(t_id: str, action: str, phone: str) -> dict:
    txn = txn_mgr.get_transaction(t_id)
    if not txn or txn.type != "REQUEST" or txn.sender_phone != phone:
        raise HTTPException(status_code=404, detail="Request not found")
    ok, msg = txn_mgr.process_request(t_id, action)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/me/requests/{t_id}/pay", tags=["app"])
def app_pay_request(t_id: str, phone: str = APP_AUTH):
    """Pay an incoming money request (the authenticated user is the payer)."""
    return _process_request_for(t_id, "PAY", phone)


@app.post("/me/requests/{t_id}/decline", tags=["app"])
def app_decline_request(t_id: str, phone: str = APP_AUTH):
    """Decline an incoming money request."""
    return _process_request_for(t_id, "DECLINE", phone)


class AppPayBillRequest(BaseModel):
    biller_id: int
    amount: float
    description: str = "Bill Payment"


def _resolve_biller(biller_id: int) -> dict:
    biller = next((b for b in biller_mgr.list(active_only=True) if b["id"] == biller_id), None)
    if not biller:
        raise HTTPException(status_code=404, detail="Biller not found")
    return biller


@app.get("/billers", tags=["app"])
def app_list_billers(phone: str = APP_AUTH):
    """Active biller catalog + categories for the Pay Bills screen."""
    return {"categories": list(CATEGORIES), "billers": biller_mgr.list(active_only=True)}


@app.post("/me/pay-bill", tags=["app"])
def app_pay_bill(req: AppPayBillRequest, phone: str = APP_AUTH):
    """Pay a bill to a registered biller (resolved from the catalog by id)."""
    biller = _resolve_biller(req.biller_id)
    ok, msg = txn_mgr.pay_bill(phone, req.amount, str(biller["name"]), str(biller["biller_id"]), req.description)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


# --- Beneficiaries --------------------------------------------------------------

class AppBeneficiaryRequest(BaseModel):
    phone: str
    nickname: str = ""


@app.get("/me/beneficiaries", tags=["app"])
def app_list_beneficiaries(phone: str = APP_AUTH):
    return {"beneficiaries": beneficiary_mgr.list(phone)}


@app.post("/me/beneficiaries", tags=["app"])
def app_add_beneficiary(req: AppBeneficiaryRequest, phone: str = APP_AUTH):
    ok, msg = beneficiary_mgr.add(phone, req.phone, req.nickname)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.delete("/me/beneficiaries/{beneficiary_phone}", tags=["app"])
def app_remove_beneficiary(beneficiary_phone: str, phone: str = APP_AUTH):
    if not beneficiary_mgr.remove(phone, beneficiary_phone):
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    return {"message": "Beneficiary removed"}


@app.get("/me/recent-recipients", tags=["app"])
def app_recent_recipients(phone: str = APP_AUTH):
    return {"recipients": beneficiary_mgr.recent_recipients(phone)}


# --- History --------------------------------------------------------------------

@app.get("/me/history", tags=["app"])
def app_history(phone: str = APP_AUTH, limit: int = Query(50, ge=1, le=200)):
    """Transaction history, newest first."""
    return {"transactions": [t.to_dict() for t in txn_mgr.get_history(phone)[:limit]]}


# --- Scheduled payments -----------------------------------------------------------

class AppScheduledRequest(BaseModel):
    type: str                     # "TRANSFER" or "BILL_PAYMENT"
    amount: float
    description: str = ""
    receiver_phone: str = ""
    biller_id: int | None = None  # catalog id — required for BILL_PAYMENT
    frequency: str = "once"       # once | daily | weekly | monthly
    start_at: str | None = None


@app.get("/me/scheduled", tags=["app"])
def app_list_scheduled(phone: str = APP_AUTH):
    return {"scheduled": scheduled_mgr.list(phone)}


@app.post("/me/scheduled", tags=["app"])
def app_create_scheduled(req: AppScheduledRequest, phone: str = APP_AUTH):
    biller_name = biller_code = ""
    if req.type == "BILL_PAYMENT":
        if req.biller_id is None:
            raise HTTPException(status_code=400, detail="biller_id is required for BILL_PAYMENT")
        biller = _resolve_biller(req.biller_id)
        biller_name, biller_code = str(biller["name"]), str(biller["biller_id"])
    ok, msg = scheduled_mgr.create(phone, req.type, req.amount, req.description,
                                   req.receiver_phone, biller_name, biller_code,
                                   req.frequency, req.start_at)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.post("/me/scheduled/{sp_id}/cancel", tags=["app"])
def app_cancel_scheduled(sp_id: int, phone: str = APP_AUTH):
    ok, msg = scheduled_mgr.cancel(phone, sp_id)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"message": msg}


class ScheduledActiveRequest(BaseModel):
    active: bool


@app.patch("/me/scheduled/{sp_id}", tags=["app"])
def app_set_scheduled_active(sp_id: int, req: ScheduledActiveRequest, phone: str = APP_AUTH):
    ok, msg = scheduled_mgr.set_active(phone, sp_id, req.active)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"message": msg}


# --- Support tickets --------------------------------------------------------------

class AppTicketRequest(BaseModel):
    subject: str
    category: str                 # payment | account | kyc | security | other
    message: str
    priority: str = "normal"      # low | normal | high


@app.get("/me/tickets", tags=["app"])
def app_list_tickets(phone: str = APP_AUTH):
    return {"tickets": ticket_mgr.my_tickets(phone)}


@app.post("/me/tickets", tags=["app"])
def app_create_ticket(req: AppTicketRequest, phone: str = APP_AUTH):
    ok, msg = ticket_mgr.create(phone, req.subject, req.category, req.message, req.priority)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.get("/me/tickets/{ticket_id}", tags=["app"])
def app_get_ticket(ticket_id: int, phone: str = APP_AUTH):
    ticket = ticket_mgr.get(ticket_id)
    if not ticket or ticket["phone"] != phone:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# --- Profile, KYC, privacy --------------------------------------------------------

class AppKycRequest(BaseModel):
    id_type: str
    id_number: str


@app.post("/me/kyc", tags=["app"])
def app_submit_kyc(req: AppKycRequest, phone: str = APP_AUTH):
    """Submit KYC identity verification from the app."""
    ok, msg = user_mgr.submit_kyc(phone, req.id_type, req.id_number)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.get("/me/data-export", tags=["app"])
def app_data_export(phone: str = APP_AUTH):
    """Privacy data export: everything the platform holds about the user."""
    data = privacy_mgr.export_user_data(phone)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return data
