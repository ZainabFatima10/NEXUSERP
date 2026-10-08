"""
NEXUS ERP — Vendor payout accounts (step M's destination resolver)
Fills the gap left by vendors.bank_name/bank_account_title/bank_iban
(migration 009): those are the vendor's informal Commercial-Terms contact
banking details, lightly validated, stored in plaintext, and read in a
handful of display/CSV spots — left completely untouched by this module.

This module is the verified, encrypted-at-rest payout destination for
real money movement: payments.py's release_payout() ("step M") calls
get_vendor_payout_destination() here, which only ever returns a value once
an admin has marked the account 'verified'. See VENDOR_PAYOUT_ACCOUNTS.md
for the full data model, masking/encryption approach, and the step-M
integration point.

One row per vendor_applications row (application_id UNIQUE), reassigned —
never duplicated — to vendor_id once that application is approved
(reassign_to_vendor(), called from vendors.approve_vendor_application()).

No router of its own: the handful of HTTP endpoints this needs
(reveal/verify/reject, the two public constant-list endpoints) are added
directly onto vendors.py's existing router, since they're siblings of the
vendor-application endpoints already there. Importable by both vendors.py
(registration + vetting) and payments.py (step M) without pulling FastAPI
routing into the latter.
"""
import hashlib
import hmac
import os
import re
import uuid
from typing import List, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from pk_banks import PK_BANKS, WALLET_PROVIDERS

VENDOR_PAYOUT_ENCRYPTION_KEY = os.getenv("VENDOR_PAYOUT_ENCRYPTION_KEY", "")
VENDOR_PAYOUT_HASH_KEY = os.getenv("VENDOR_PAYOUT_HASH_KEY", "")

PAYOUT_METHODS = {"bank_account", "mobile_wallet"}


class VendorPayoutAccountMissing(RuntimeError):
    """Raised by get_vendor_payout_destination() when step M has nothing
    (or nothing verified) to pay out to. Not an HTTPException — this is a
    service-layer function called from payments.py, not a route."""


# ────────────────────────────────────────────────────────────────────────────
# Encryption (Fernet, lazy-init) + duplicate-detection hashing (HMAC-SHA256)
# Mirrors shipment_chain_service.py's _fernet() pattern exactly, with its
# own key — a different trust domain from the per-user chain wallet keys.
# ────────────────────────────────────────────────────────────────────────────
_fernet_instance = None


def _fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    from cryptography.fernet import Fernet
    key = VENDOR_PAYOUT_ENCRYPTION_KEY
    if not key:
        key = Fernet.generate_key().decode()
        print("[WARN] VENDOR_PAYOUT_ENCRYPTION_KEY not set — generated an in-memory key for this process only. "
              "Vendor payout accounts created now will be unreadable after a restart. Set "
              "VENDOR_PAYOUT_ENCRYPTION_KEY in .env for any persistent deployment.")
    _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet_instance


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


_hash_key_warned = False


def _hash(value: str) -> str:
    """Non-reversible lookup key for cross-vendor duplicate detection — lets
    the database reject a duplicate IBAN/wallet number via a unique index
    without ever comparing decrypted values in application code."""
    global _hash_key_warned
    key = VENDOR_PAYOUT_HASH_KEY
    if not key:
        key = "dev-only-insecure-hash-key-set-VENDOR_PAYOUT_HASH_KEY-in-env"
        if not _hash_key_warned:
            print("[WARN] VENDOR_PAYOUT_HASH_KEY not set — using an insecure fallback key for duplicate-account "
                  "detection. Set VENDOR_PAYOUT_HASH_KEY in .env for any persistent deployment.")
            _hash_key_warned = True
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def _masked(last4: Optional[str]) -> Optional[str]:
    return f"••••{last4}" if last4 else None


# ────────────────────────────────────────────────────────────────────────────
# Normalization + validation — the source of truth; the frontend only mirrors it
# ────────────────────────────────────────────────────────────────────────────

def _normalize_title(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip())


def normalize_iban(raw: str) -> str:
    return (raw or "").strip().upper().replace(" ", "")


_IBAN_FORMAT = re.compile(r"^PK\d{2}[A-Z]{4}[A-Z0-9]{16}$")


def iban_checksum_valid(iban: str) -> bool:
    """ISO 13616 / mod-97 check. `iban` must already be the normalized
    (uppercase, no-spaces) 24-character string."""
    if not _IBAN_FORMAT.match(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = ""
    for ch in rearranged:
        digits += ch if ch.isdigit() else str(ord(ch) - ord("A") + 10)
    return int(digits) % 97 == 1


def normalize_wallet_number(raw: str) -> str:
    """+92XXXXXXXXXX / 0092XXXXXXXXXX / spaces / dashes -> 03XXXXXXXXX."""
    s = re.sub(r"[\s-]", "", raw or "")
    if s.startswith("+92"):
        s = "0" + s[3:]
    elif s.startswith("0092"):
        s = "0" + s[4:]
    elif s.startswith("92") and len(s) == 12:
        s = "0" + s[2:]
    return s


_WALLET_FORMAT = re.compile(r"^03\d{9}$")


class VendorPaymentAccountCreate(BaseModel):
    payout_method: str  # bank_account | mobile_wallet
    account_title: str
    bank_name: Optional[str] = None
    branch_code: Optional[str] = None
    iban: Optional[str] = None
    account_number: Optional[str] = None
    wallet_provider: Optional[str] = None
    wallet_number: Optional[str] = None


def validate_payout_account(p: VendorPaymentAccountCreate) -> Tuple[List[str], Optional[str]]:
    """Returns (errors, warning). Non-empty errors means the whole
    registration is rejected (422) — nothing is persisted. `warning` is
    informational only (e.g. an IBAN/bank-name mismatch) and never blocks."""
    errors: List[str] = []
    warning: Optional[str] = None

    if p.payout_method not in PAYOUT_METHODS:
        return ([f"payout_method must be one of {sorted(PAYOUT_METHODS)}"], None)

    title = _normalize_title(p.account_title)
    if not (3 <= len(title) <= 100) or not re.match(r"^[A-Za-z .'\-]+$", title):
        errors.append("account_title must be 3-100 characters, letters/spaces/.,-,' only")

    if p.payout_method == "bank_account":
        if p.wallet_provider or p.wallet_number:
            errors.append("wallet_provider/wallet_number must not be set for a bank_account payout")
        if not (p.bank_name or "").strip():
            errors.append("bank_name is required for a bank account")
        elif p.bank_name not in PK_BANKS:
            errors.append(f"bank_name must be one of the listed banks (got {p.bank_name!r})")
        if not (p.iban or "").strip():
            errors.append("iban is required for a bank account")
        else:
            iban = normalize_iban(p.iban)
            if not _IBAN_FORMAT.match(iban):
                errors.append("iban must be a 24-character Pakistani IBAN (PK + 2 digits + 4-letter bank code + 16 alphanumeric)")
            elif not iban_checksum_valid(iban):
                errors.append("iban fails the standard IBAN checksum — double-check it was entered correctly")
            elif p.bank_name in PK_BANKS and iban[4:8] != PK_BANKS[p.bank_name]:
                warning = (f"The IBAN's bank code ({iban[4:8]}) doesn't match the usual code for "
                           f"{p.bank_name} ({PK_BANKS[p.bank_name]}) — double-check it, but this isn't blocking.")
        if p.account_number:
            digits = re.sub(r"\D", "", p.account_number)
            if not (8 <= len(digits) <= 20):
                errors.append("account_number must be 8-20 digits")

    else:  # mobile_wallet
        if p.bank_name or p.branch_code or p.iban or p.account_number:
            errors.append("bank_name/branch_code/iban/account_number must not be set for a mobile_wallet payout")
        if (p.wallet_provider or "") not in WALLET_PROVIDERS:
            errors.append(f"wallet_provider must be one of {sorted(WALLET_PROVIDERS)}")
        if not (p.wallet_number or "").strip():
            errors.append("wallet_number is required for a mobile wallet")
        else:
            wallet = normalize_wallet_number(p.wallet_number)
            if not _WALLET_FORMAT.match(wallet):
                errors.append("wallet_number must be a valid Pakistani mobile number (e.g. 03XXXXXXXXX)")

    return errors, warning


# ────────────────────────────────────────────────────────────────────────────
# Persistence — called from vendors.py, inside its existing transaction
# ────────────────────────────────────────────────────────────────────────────

def create_payment_account_for_application(db: Session, application_id: str, p: VendorPaymentAccountCreate) -> str:
    """Validates, checks cross-vendor duplicates, encrypts, and INSERTs.
    Raises HTTPException (422 invalid, 409 duplicate) and writes nothing on
    failure — the caller's transaction is still open, so the vendor
    application itself is never created either. No commit here."""
    errors, _warning = validate_payout_account(p)
    if errors:
        raise HTTPException(422, "; ".join(errors))

    account_id = str(uuid.uuid4())
    title = _normalize_title(p.account_title)
    row = {
        "id": account_id, "aid": application_id, "method": p.payout_method, "title": title,
        "bank": None, "branch": None,
        "iban_enc": None, "iban_last4": None, "iban_hash": None,
        "acct_enc": None, "acct_last4": None,
        "wallet_provider": None, "wallet_enc": None, "wallet_last4": None, "wallet_hash": None,
    }

    if p.payout_method == "bank_account":
        iban = normalize_iban(p.iban)
        iban_hash = _hash(iban)
        dup = db.execute(text("SELECT 1 FROM vendor_payment_accounts WHERE iban_hash = :h"), {"h": iban_hash}).first()
        if dup:
            raise HTTPException(409, "This IBAN is already registered with another vendor.")
        row.update({
            "bank": p.bank_name.strip(), "branch": (p.branch_code or "").strip() or None,
            "iban_enc": _encrypt(iban), "iban_last4": iban[-4:], "iban_hash": iban_hash,
        })
        if p.account_number:
            digits = re.sub(r"\D", "", p.account_number)
            row.update({"acct_enc": _encrypt(digits), "acct_last4": digits[-4:]})
    else:
        wallet = normalize_wallet_number(p.wallet_number)
        wallet_hash = _hash(wallet)
        dup = db.execute(text("SELECT 1 FROM vendor_payment_accounts WHERE wallet_hash = :h"), {"h": wallet_hash}).first()
        if dup:
            raise HTTPException(409, "This mobile wallet number is already registered with another vendor.")
        row.update({
            "wallet_provider": p.wallet_provider, "wallet_enc": _encrypt(wallet),
            "wallet_last4": wallet[-4:], "wallet_hash": wallet_hash,
        })

    db.execute(
        text("""
            INSERT INTO vendor_payment_accounts (
              id, application_id, payout_method, account_title, bank_name, branch_code,
              iban_encrypted, iban_last4, iban_hash, account_number_encrypted, account_number_last4,
              wallet_provider, wallet_number_encrypted, wallet_last4, wallet_hash
            ) VALUES (
              :id, :aid, :method, :title, :bank, :branch,
              :iban_enc, :iban_last4, :iban_hash, :acct_enc, :acct_last4,
              :wallet_provider, :wallet_enc, :wallet_last4, :wallet_hash
            )
        """),
        row,
    )
    return account_id


def _masked_out(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "payout_method": row["payout_method"],
        "account_title": row["account_title"],
        "bank_name": row["bank_name"],
        "branch_code": row["branch_code"],
        "iban_masked": _masked(row["iban_last4"]),
        "account_number_masked": _masked(row["account_number_last4"]),
        "wallet_provider": row["wallet_provider"],
        "wallet_number_masked": _masked(row["wallet_last4"]),
        "verification_status": row["verification_status"],
        "verified_at": row["verified_at"],
        "rejection_reason": row["rejection_reason"],
    }


def account_for_application(db: Session, application_id: str) -> Optional[dict]:
    """Masked summary for the admin vetting view — None if nothing on file."""
    row = db.execute(
        text("SELECT * FROM vendor_payment_accounts WHERE application_id = :aid"), {"aid": application_id}
    ).mappings().first()
    return _masked_out(dict(row)) if row else None


def is_verified_for_application(db: Session, application_id: str) -> bool:
    status = db.execute(
        text("SELECT verification_status FROM vendor_payment_accounts WHERE application_id = :aid"), {"aid": application_id}
    ).scalar()
    return status == "verified"


def reassign_to_vendor(db: Session, application_id: str, vendor_id: str):
    """Called once, right after the vendor row is INSERTed in the same
    transaction as vendors.approve_vendor_application() — the account
    follows its application to the new vendor rather than being copied."""
    db.execute(
        text("UPDATE vendor_payment_accounts SET vendor_id = :vid, updated_at = NOW() WHERE application_id = :aid"),
        {"vid": vendor_id, "aid": application_id},
    )


def _get_account_by_application(db: Session, application_id: str) -> dict:
    row = db.execute(
        text("SELECT * FROM vendor_payment_accounts WHERE application_id = :aid"), {"aid": application_id}
    ).mappings().first()
    if not row:
        raise HTTPException(404, "No payout account on file for this application")
    return dict(row)


def _audit(db: Session, account_id, action: str, actor_id: Optional[str], note: Optional[str] = None):
    db.execute(
        text("""
            INSERT INTO vendor_payment_account_audit_log (id, account_id, action, actor_id, note)
            VALUES (:id, :aid, :action, :actor, :note)
        """),
        {"id": str(uuid.uuid4()), "aid": str(account_id), "action": action, "actor": actor_id, "note": note},
    )


def reveal_account(db: Session, application_id: str, actor_user_id: str) -> dict:
    """The one path (besides step M itself) allowed to see the unmasked
    value — restricted to admin at the route level, audit-logged here."""
    row = _get_account_by_application(db, application_id)
    out = {
        "payout_method": row["payout_method"], "account_title": row["account_title"],
        "bank_name": row["bank_name"], "branch_code": row["branch_code"],
        "wallet_provider": row["wallet_provider"],
    }
    if row["payout_method"] == "bank_account":
        out["iban"] = _decrypt(row["iban_encrypted"]) if row["iban_encrypted"] else None
        out["account_number"] = _decrypt(row["account_number_encrypted"]) if row["account_number_encrypted"] else None
    else:
        out["wallet_number"] = _decrypt(row["wallet_number_encrypted"]) if row["wallet_number_encrypted"] else None
    _audit(db, row["id"], "reveal", actor_user_id)
    return out


def verify_account(db: Session, application_id: str, actor_user_id: str):
    row = _get_account_by_application(db, application_id)
    db.execute(
        text("""
            UPDATE vendor_payment_accounts
            SET verification_status = 'verified', verified_by = :uid, verified_at = NOW(),
                rejection_reason = NULL, updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": actor_user_id, "id": row["id"]},
    )
    _audit(db, row["id"], "verify", actor_user_id)


def reject_account(db: Session, application_id: str, actor_user_id: str, reason: str):
    row = _get_account_by_application(db, application_id)
    db.execute(
        text("""
            UPDATE vendor_payment_accounts
            SET verification_status = 'rejected', verified_by = :uid, verified_at = NOW(),
                rejection_reason = :r, updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": actor_user_id, "r": reason, "id": row["id"]},
    )
    _audit(db, row["id"], "reject", actor_user_id, note=reason)


# ────────────────────────────────────────────────────────────────────────────
# Step M integration point — called from payments.release_payout()
# ────────────────────────────────────────────────────────────────────────────

def get_vendor_payout_destination(db: Session, vendor_id: str) -> dict:
    """The only function payments.py (step M) calls to find out where the
    money goes. Raises VendorPayoutAccountMissing — never silently returns
    an unverified or absent destination — if there's nothing to pay out to
    yet; the caller is responsible for putting the payment into the
    existing 'blocked' state and notifying an admin (see payments.py)."""
    row = db.execute(
        text("SELECT * FROM vendor_payment_accounts WHERE vendor_id = :vid"), {"vid": vendor_id}
    ).mappings().first()
    if not row or row["verification_status"] != "verified":
        raise VendorPayoutAccountMissing(
            "No verified payout account on file for this vendor. Add and verify one under Vendor Applications."
        )
    row = dict(row)
    destination = {
        "payout_method": row["payout_method"],
        "account_title": row["account_title"],
        "bank_name": row["bank_name"],
    }
    if row["payout_method"] == "bank_account":
        destination["identifier"] = _decrypt(row["iban_encrypted"])
        destination["masked_identifier"] = _masked(row["iban_last4"])
    else:
        destination["identifier"] = _decrypt(row["wallet_number_encrypted"])
        destination["masked_identifier"] = _masked(row["wallet_last4"])
        destination["wallet_provider"] = row["wallet_provider"]
    return destination
