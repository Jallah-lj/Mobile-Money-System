from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
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

class TransactionRequest(BaseModel):
    phone: str
    amount: float
    description: str = ""

class TransferRequest(BaseModel):
    sender_phone: str
    receiver_phone: str
    amount: float
    description: str = ""

@app.post("/users/register")
def register(req: RegisterRequest):
    success, msg = user_mgr.register(req.phone, req.name, req.pin, req.sec_q, req.sec_a, req.currency)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/users/{phone}/kyc")
def submit_kyc(phone: str, req: KYCRequest):
    if phone != req.phone:
        raise HTTPException(status_code=400, detail="Phone mismatch")
    success, msg = user_mgr.submit_kyc(req.phone, req.id_type, req.id_number)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.get("/users/{phone}")
def get_user(phone: str):
    user = user_mgr.get_user(phone)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()

@app.post("/transactions/deposit")
def deposit(req: TransactionRequest):
    success, msg = txn_mgr.deposit(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/transactions/withdraw")
def withdraw(req: TransactionRequest):
    success, msg = txn_mgr.withdraw(req.phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/transactions/transfer")
def transfer(req: TransferRequest):
    success, msg = txn_mgr.transfer(req.sender_phone, req.receiver_phone, req.amount, req.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.get("/transactions/{phone}/history")
def get_history(phone: str):
    txns = txn_mgr.get_history(phone)
    return [t.to_dict() for t in txns]
