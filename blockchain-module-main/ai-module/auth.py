"""
NEXUS ERP — Auth Router (DB-backed)
Replaces the mock AuthContext login with real bcrypt-verified login.
Issues a JWT (see rbac.py) instead of the old opaque session token so
role can be verified server-side on every request without a DB round-trip.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import text
import bcrypt
from database import get_db
from rbac import (
    create_access_token,
    get_current_user,
    require_role,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ADMIN_SIDE_ROLES,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False

def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


class LoginRequest(BaseModel):
    email:    str
    password: str


class SignupRequest(BaseModel):
    name:     str
    email:    str
    password: str
    # role is intentionally NOT accepted here — public self-signup only ever
    # creates a "customer" (Customer Portal) account. Admin/CR/Procurement
    # Manager accounts are provisioned via migration seed or POST /admin-create
    # below by an existing Admin. Accepting a client-supplied role on public
    # signup would let anyone self-elevate to Admin.


class AdminCreateUserRequest(BaseModel):
    name:     str
    email:    str
    password: str
    role:     str   # customer_rep | procurement_manager | admin


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT * FROM users WHERE email=:e AND is_active=TRUE"),
        {"e": req.email},
    ).mappings().first()
    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    user = {
        "id":    str(row["id"]),
        "name":  row["name"],
        "email": row["email"],
        "role":  row["role"],
    }
    token = create_access_token(user["id"], user["email"], user["name"], user["role"])
    return {"user": user, "token": token}


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    """Public signup — always creates a Customer Portal account (role=customer)."""
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
            "hash":  hash_password(req.password),
            "role":  ROLE_CUSTOMER,
        },
    )
    db.commit()
    return {"message": "Account created", "user_id": uid}


@router.post("/admin-create-user", dependencies=[Depends(require_role(ROLE_ADMIN))])
def admin_create_user(req: AdminCreateUserRequest, db: Session = Depends(get_db)):
    """Admin-only: provision a new Customer Rep / Procurement Manager / Admin account."""
    if req.role not in ADMIN_SIDE_ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ADMIN_SIDE_ROLES)}")
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
            "hash":  hash_password(req.password),
            "role":  req.role,
        },
    )
    db.commit()
    return {"message": "Account created", "user_id": uid}


@router.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    return user
