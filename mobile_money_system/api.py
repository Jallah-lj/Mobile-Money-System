"""FastAPI REST API for the Mobile Money System.

Security model:
  * If the MMS_API_KEY environment variable is set, every endpoint (except
    /health) requires an `X-API-Key` header matching it.
  * If it is not set, the API runs in open "development mode" and prints a
    warning at startup. Never deploy without setting a key.
  * User responses never expose PIN hashes or security answers.
"""

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

try:
    from .audit import get_audit_logs
    from .privacy import PrivacyManager
    from .transactions import TransactionManager
    from .users import UserManager
except ImportError:
    # Dual import path: this module is also runnable as a top-level script module.
    from audit import get_audit_logs  # type: ignore[no-redef]
    from privacy import PrivacyManager  # type: ignore[no-redef]
    from transactions import TransactionManager  # type: ignore[no-redef]
    from users import UserManager  # type: ignore[no-redef]

API_KEY_NAME = "X-API-Key"
API_KEY_ENV_VAR = "MMS_API_KEY"
EXPECTED_API_KEY = os.environ.get(API_KEY_ENV_VAR)


# --- Rate limiting -----------------------------------------------------------
# Sliding-window, in-memory limiter. Per-endpoint-class limits protect the API
# from brute-force and abuse without any external dependencies. (Account-level
# lockout for logins is additionally enforced by UserManager.)
class RateLimiter:
    """Sliding-window rate limiter: at most `max_requests` per `window_seconds`."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Record a hit for `key`. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                retry_after = int(self.window_seconds - (now - hits[0])) + 1
                return False, max(retry_after, 1)
            hits.append(now)
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# Per-IP limits per endpoint class
GENERAL_LIMIT = (120, 60)    # 120 requests/minute per client IP
LOGIN_LIMIT = (10, 60)       # 10 login attempts/minute per client IP
REGISTER_LIMIT = (20, 60)    # 20 registrations/minute per client IP

_general_limiter = RateLimiter(*GENERAL_LIMIT)
_login_limiter = RateLimiter(*LOGIN_LIMIT)
_register_limiter = RateLimiter(*REGISTER_LIMIT)

RATE_LIMIT_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


app = FastAPI(
    title="Mobile Money System API",
    description="REST API for wallet operations and compliance audit trails.",
    version="2.0.0",
)

# Singletons for the app lifecycle
user_mgr = UserManager()
txn_mgr = TransactionManager(user_mgr)
privacy_mgr = PrivacyManager()

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
    if path == "/users/login":
        endpoint_limiter = _login_limiter
    elif path == "/users/register":
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
    """Liveness probe — always unauthenticated."""
    return {"status": "ok", "auth_required": EXPECTED_API_KEY is not None}


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
def transfer(req: TransferRequest):
    success, msg = txn_mgr.transfer(req.sender_phone, req.receiver_phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


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
