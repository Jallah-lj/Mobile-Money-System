import os
import re
from fastapi import FastAPI, HTTPException, Body, Depends, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, field_validator
from typing import Optional, List
try:
    from .users import UserManager
    from .transactions import TransactionManager
except ImportError:
    from users import UserManager
    from transactions import TransactionManager

app = FastAPI(title="Mobile Money API")

# Singletons for the app lifecycle
user_mgr = UserManager()
txn_mgr = TransactionManager(user_mgr)

# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------
_API_KEY_NAME = "X-API-Key"
_api_key_header = APIKeyHeader(name=_API_KEY_NAME, auto_error=True)

def _get_configured_api_key() -> str:
    """Return the expected API key from the environment (required)."""
    key = os.environ.get("API_KEY", "")
    if not key:
        raise RuntimeError("API_KEY environment variable is not set. Set it before starting the API server.")
    return key

async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    if api_key != _get_configured_api_key():
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key

# ---------------------------------------------------------------------------
# Phone validation helper
# ---------------------------------------------------------------------------
_PHONE_RE = re.compile(r'^\d{10,15}$')

def _validate_phone_str(v: str) -> str:
    if not _PHONE_RE.match(v):
        raise ValueError("Phone must be 10–15 digits")
    return v

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    phone: str
    name: str
    pin: str
    sec_q: str
    sec_a: str
    currency: str = "USD"

    @field_validator("phone")
    @classmethod
    def phone_must_be_digits(cls, v: str) -> str:
        return _validate_phone_str(v)

    @field_validator("pin")
    @classmethod
    def pin_length(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("PIN must be at least 4 characters")
        return v

class KYCRequest(BaseModel):
    phone: str
    id_type: str
    id_number: str

    @field_validator("phone")
    @classmethod
    def phone_must_be_digits(cls, v: str) -> str:
        return _validate_phone_str(v)

class TransactionRequest(BaseModel):
    phone: str
    amount: float
    description: str = ""

    @field_validator("phone")
    @classmethod
    def phone_must_be_digits(cls, v: str) -> str:
        return _validate_phone_str(v)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be greater than zero")
        return v

class TransferRequest(BaseModel):
    sender_phone: str
    receiver_phone: str
    amount: float
    description: str = ""

    @field_validator("sender_phone", "receiver_phone")
    @classmethod
    def phone_must_be_digits(cls, v: str) -> str:
        return _validate_phone_str(v)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Amount must be greater than zero")
        return v

@app.post("/users/register", dependencies=[Depends(require_api_key)])
def register(req: RegisterRequest):
    success, msg = user_mgr.register(req.phone, req.name, req.pin, req.sec_q, req.sec_a, req.currency)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/users/{phone}/kyc", dependencies=[Depends(require_api_key)])
def submit_kyc(phone: str, req: KYCRequest):
    if phone != req.phone:
        raise HTTPException(status_code=400, detail="Phone mismatch")
    success, msg = user_mgr.submit_kyc(req.phone, req.id_type, req.id_number)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.get("/users/{phone}", dependencies=[Depends(require_api_key)])
def get_user(phone: str):
    user = user_mgr.get_user(phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Return only non-sensitive fields; never expose pin or security answer hashes
    data = user.to_dict()
    data.pop("pin", None)
    data.pop("sec_a", None)
    return data

@app.post("/transactions/deposit", dependencies=[Depends(require_api_key)])
def deposit(req: TransactionRequest):
    success, msg = txn_mgr.deposit(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/transactions/withdraw", dependencies=[Depends(require_api_key)])
def withdraw(req: TransactionRequest):
    success, msg = txn_mgr.withdraw(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/transactions/transfer", dependencies=[Depends(require_api_key)])
def transfer(req: TransferRequest):
    success, msg = txn_mgr.transfer(req.sender_phone, req.receiver_phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.get("/transactions/{phone}/history", dependencies=[Depends(require_api_key)])
def get_history(phone: str):
    txns = txn_mgr.get_history(phone)
    return [t.to_dict() for t in txns]
