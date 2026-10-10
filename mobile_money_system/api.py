"""FastAPI REST API for the Mobile Money System.

Security model:
  * If the MMS_API_KEY environment variable is set, every endpoint (except
    /health) requires an `X-API-Key` header matching it.
  * If it is not set, the API runs in open "development mode" and prints a
    warning at startup. Never deploy without setting a key.
  * User responses never expose PIN hashes or security answers.
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Body, Header, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

try:
    from .users import UserManager
    from .transactions import TransactionManager
    from .audit import get_audit_logs
except ImportError:
    from users import UserManager
    from transactions import TransactionManager
    from audit import get_audit_logs

API_KEY_NAME = "X-API-Key"
API_KEY_ENV_VAR = "MMS_API_KEY"
EXPECTED_API_KEY = os.environ.get(API_KEY_ENV_VAR)

app = FastAPI(
    title="Mobile Money System API",
    description="REST API for wallet operations and compliance audit trails.",
    version="2.0.0",
)

# Singletons for the app lifecycle
user_mgr = UserManager()
txn_mgr = TransactionManager(user_mgr)

api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    """Enforce API key auth when MMS_API_KEY is configured."""
    if EXPECTED_API_KEY is None:
        return  # Development mode (a warning is printed at startup)
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


AUTH = Security(verify_api_key)

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


@app.get("/admin/audit", dependencies=[AUTH], tags=["admin"])
def audit_log(limit: int = Query(200, ge=1, le=1000),
              actor: Optional[str] = Query(None),
              action: Optional[str] = Query(None)):
    """Compliance audit trail, newest first, with optional filters."""
    return [e.to_dict() for e in get_audit_logs(limit=limit, actor_phone=actor, action=action)]
