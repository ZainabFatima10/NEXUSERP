"""
NEXUS ERP — RBAC / JWT Auth Helpers
Layered on top of the existing bcrypt-based auth (auth.py) — does not
replace the users table or password flow, only how identity/role is
carried on the request and enforced per-endpoint.

Roles:
  admin                — full access to every module/dashboard/endpoint
  customer_rep         — complaints/tickets (VEMA + manual), resolve, escalate
  procurement_manager  — inventory reorder approvals, vendor comms, orders
  customer             — external portal user (voice/chat complaint intake only)
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from jose import jwt, JWTError

ROLE_ADMIN = "admin"
ROLE_CUSTOMER_REP = "customer_rep"
ROLE_PROCUREMENT_MANAGER = "procurement_manager"
ROLE_CUSTOMER = "customer"

ADMIN_SIDE_ROLES = {ROLE_ADMIN, ROLE_CUSTOMER_REP, ROLE_PROCUREMENT_MANAGER}
ALL_ROLES = ADMIN_SIDE_ROLES | {ROLE_CUSTOMER}

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24h

if JWT_SECRET_KEY == "dev-insecure-secret-change-me":
    print("[WARN] JWT_SECRET_KEY not set in .env — using an insecure dev default. "
          "Set a real secret before deploying.")


def create_access_token(user_id: str, email: str, name: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    return auth_header[len("Bearer "):]


def get_current_user(request: Request) -> dict:
    """FastAPI dependency — decodes the JWT and returns {id, email, name, role}."""
    token = _extract_bearer_token(request)
    payload = decode_access_token(token)
    return {
        "id": payload["sub"],
        "email": payload["email"],
        "name": payload["name"],
        "role": payload["role"],
    }


def get_current_user_optional(request: Request) -> Optional[dict]:
    """Same as get_current_user but returns None instead of raising when no/invalid token."""
    try:
        return get_current_user(request)
    except HTTPException:
        return None


def require_role(*roles: str):
    """
    Dependency factory. Usage:
        @router.get("/x", dependencies=[Depends(require_role("admin", "procurement_manager"))])
    Admin is always implicitly allowed unless explicitly excluded via require_role_strict.
    """
    allowed = set(roles) | {ROLE_ADMIN}

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(403, f"Role '{user['role']}' is not permitted to perform this action")
        return user

    return _checker


def require_role_strict(*roles: str):
    """Same as require_role but does NOT implicitly allow admin (rarely needed)."""
    allowed = set(roles)

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(403, f"Role '{user['role']}' is not permitted to perform this action")
        return user

    return _checker
