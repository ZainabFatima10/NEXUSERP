"""
NEXUS ERP — Auth Router (DB-backed)
Replaces the mock AuthContext login with real bcrypt-verified login.
Returns a simple session token stored client-side.
"""
import uuid, secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import text
from passlib.context import CryptContext
from database import get_db

router = APIRouter(prefix="/api/auth", tags=["Auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginRequest(BaseModel):
    email:    str
    password: str


class SignupRequest(BaseModel):
    name:     str
    email:    str
    password: str
    role:     str = "Operator"


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT * FROM users WHERE email=:e AND is_active=TRUE"),
        {"e": req.email},
    ).mappings().first()
    if not row or not pwd_ctx.verify(req.password, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {
        "user": {
            "id":    str(row["id"]),
            "name":  row["name"],
            "email": row["email"],
            "role":  row["role"],
        },
        "token": secrets.token_urlsafe(32),   # use JWT in production
    }


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    exists = db.execute(
        text("SELECT id FROM users WHERE email=:e"), {"e": req.email}
    ).first()
    if exists:
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO users (id, name, email, password_hash, role)
            VALUES (:id, :name, :email, :hash, :role)
        """),
        {
            "id":    uid,
            "name":  req.name,
            "email": req.email,
            "hash":  pwd_ctx.hash(req.password),
            "role":  req.role,
        },
    )
    db.commit()
    return {"message": "Account created", "user_id": uid}


@router.get("/me")
def get_me(user_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, name, email, role FROM users WHERE id=:id"),
        {"id": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row)
