"""
NEXUS ERP — Vendor Registration, Vetting & Approved Catalogue
Phase 1 of the vendor/procurement/shipment/payment expansion (see
VENDOR_ONBOARDING.md). Vendors never get a login — this router covers:

  Public (no auth):
    POST /api/public/vendors/apply          — submit a "Become a Vendor" application
    POST /api/public/vendors/items/parse    — preview-only catalogue file parse
    GET  /api/public/vendors/template       — downloadable .xlsx catalogue template
    GET  /api/public/vendors/categories     — inventory_items categories (for the multi-select)
    GET  /api/public/vendors/verify-email/{token} — one-time order-email verification link

  Admin + Procurement Manager:
    GET  /api/vendor-applications[/{id}]
    POST /api/vendor-applications/{id}/approve | reject | request-info | checklist
    GET  /api/vendors[/{id}][/items]

Does not touch contract_service.py, invoice_service.py, or any ML code.
"""
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, EmailStr, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from rbac import require_role, ROLE_PROCUREMENT_MANAGER, get_current_user
from notification_engine import notify, auto_resolve
from email_service import (
    send_vendor_application_ack,
    send_vendor_email_verification,
    send_vendor_approved_email,
    send_vendor_rejected_email,
    send_vendor_needs_info_email,
)
from vendor_catalogue_parser import parse_catalogue_file, build_template_bytes

router = APIRouter(tags=["Vendors"])
_staff = Depends(require_role(ROLE_PROCUREMENT_MANAGER))  # admin always implicitly included

VENDOR_DOCS_DIR = os.path.join(os.path.dirname(__file__), "data", "vendor_documents")
os.makedirs(VENDOR_DOCS_DIR, exist_ok=True)

MAX_DOC_BYTES = 5 * 1024 * 1024
ALLOWED_DOC_MAGIC = {
    ".pdf":  (b"%PDF",),
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png":  (b"\x89PNG\r\n\x1a\n",),
}
DOC_TYPES = {"ntn_certificate", "registration_certificate", "brochure", "authorization_letter", "other"}

# In-process sliding-window rate limit — resets on restart, per-worker only.
# Fine for this FYP's single-instance deployment; a real multi-worker
# deployment would need a shared store (Redis) instead.
_RATE_LIMIT_WINDOW_S = 3600
_RATE_LIMIT_MAX_PER_IP = 5
_rate_limit_log: dict[str, list[float]] = {}


def _check_rate_limit(ip: str):
    now = time.time()
    hits = [t for t in _rate_limit_log.get(ip, []) if now - t < _RATE_LIMIT_WINDOW_S]
    if len(hits) >= _RATE_LIMIT_MAX_PER_IP:
        raise HTTPException(429, "Too many applications submitted from this address recently — please try again later.")
    hits.append(now)
    _rate_limit_log[ip] = hits


def _validate_document(filename: str, content: bytes) -> Optional[str]:
    if len(content) > MAX_DOC_BYTES:
        return f"{filename}: exceeds the 5 MB limit"
    ext = os.path.splitext(filename.lower())[1]
    magics = ALLOWED_DOC_MAGIC.get(ext)
    if not magics:
        return f"{filename}: unsupported file type — use PDF, JPG or PNG"
    if not any(content.startswith(m) for m in magics):
        return f"{filename}: file content doesn't match its extension"
    return None


def _jsonb(value):
    """pg8000 sometimes returns JSONB as a str, sometimes already-parsed — normalize."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


# ────────────────────────────────────────────────────────────────────────────
# Pydantic models — the "Become a Vendor" application payload
# ────────────────────────────────────────────────────────────────────────────

BUSINESS_TYPES = {"Manufacturer", "Distributor", "Authorized Dealer", "Service Provider", "Other"}


class VendorApplicationItemIn(BaseModel):
    name: str
    sku: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    unit: str
    unit_price: float
    moq: Optional[float] = None
    lead_time_days: Optional[int] = None


class VendorApplicationPayload(BaseModel):
    # Step 1 — Company details
    legal_company_name: str
    trade_name: Optional[str] = None
    business_type: str
    ntn: str
    strn: Optional[str] = None
    secp_number: Optional[str] = None
    year_established: Optional[int] = None
    employee_range: Optional[str] = None
    website: Optional[str] = None
    categories: List[str] = []

    # Step 2 — Contact & location
    contact_name: str
    contact_designation: Optional[str] = None
    order_email: EmailStr
    mobile: str
    alternate_phone: Optional[str] = None
    address: str
    city: str
    province: str
    postal_code: Optional[str] = None
    coverage_provinces: List[str] = []
    coverage_cities: List[str] = []

    # Step 3 — Commercial terms
    lead_time_days: Optional[int] = None
    payment_terms: Optional[str] = None
    min_order_value: Optional[float] = None
    warranty: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_title: Optional[str] = None
    bank_iban: Optional[str] = None
    certifications: List[str] = []

    # Step 5 — Catalogue (manual + upload rows already merged client-side)
    items: List[VendorApplicationItemIn] = []

    # Step 6 — Declaration
    consent: bool
    website_hp: Optional[str] = None  # honeypot — real users never see/fill this


def _validate_payload_business_rules(p: VendorApplicationPayload) -> List[str]:
    errors = []
    if p.business_type not in BUSINESS_TYPES:
        errors.append(f"business_type must be one of {sorted(BUSINESS_TYPES)}")
    if not p.consent:
        errors.append("terms/consent must be accepted")
    if not p.items:
        errors.append("at least one catalogue item is required")
    if p.bank_iban:
        iban = p.bank_iban.strip().upper().replace(" ", "")
        if len(iban) != 24 or not iban.startswith("PK"):
            errors.append("bank_iban must be a 24-character Pakistani IBAN starting with 'PK'")
    if p.mobile and not re.match(r"^(\+92|0)[0-9]{10}$", p.mobile.replace(" ", "").replace("-", "")):
        errors.append("mobile must be a valid Pakistani number (e.g. 03XXXXXXXXX or +92XXXXXXXXXX)")
    for item in p.items:
        if item.unit_price < 0:
            errors.append(f"item '{item.name}': unit price cannot be negative")
    return errors


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/public/vendors/categories")
def public_categories(db: Session = Depends(get_db)):
    """Inventory categories, read from the DB — not a hand-maintained parallel list."""
    rows = db.execute(text("SELECT DISTINCT category FROM inventory_items ORDER BY category")).scalars().all()
    return {"categories": list(rows)}


@router.get("/api/public/vendors/template")
def public_template():
    content = build_template_bytes()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=nexus-vendor-catalogue-template.xlsx"},
    )


@router.post("/api/public/vendors/items/parse")
async def public_parse_items(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Preview-only — validates rows, stores nothing."""
    content = await file.read()
    categories = db.execute(text("SELECT DISTINCT category FROM inventory_items")).scalars().all()
    result = parse_catalogue_file(content, file.filename or "upload", list(categories))
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.get("/api/public/vendors/verify-email/{token}", response_class=HTMLResponse)
def verify_vendor_email(token: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT id, legal_company_name FROM vendor_applications WHERE email_verify_token = :t"),
        {"t": token},
    ).mappings().first()

    if not row:
        body = "<p>❌ This verification link is invalid or has already been used.</p>"
    else:
        db.execute(
            text("""
                UPDATE vendor_applications
                SET email_verified = TRUE, email_verified_at = NOW(), email_verify_token = NULL
                WHERE id = :id
            """),
            {"id": row["id"]},
        )
        db.commit()
        body = f"<p>✅ Thanks — the order email for <b>{row['legal_company_name']}</b> is now verified.</p>"

    return f"""
    <!DOCTYPE html><html>
    <head><title>NEXUS ERP — Verify Vendor Email</title>
      <style>
        body{{font-family:'DM Sans',Arial,sans-serif;background:#f4f7fb;
              display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .card{{background:#fff;border-radius:16px;padding:48px;max-width:480px;width:90%;
               box-shadow:0 8px 32px rgba(0,0,0,0.10);text-align:center}}
        h1{{color:#001F54;font-size:22px;margin-bottom:8px}}
        p{{color:#444;line-height:1.6}}
      </style>
    </head>
    <body><div class="card"><h1>NEXUS ERP</h1>{body}</div></body></html>
    """


@router.post("/api/public/vendors/apply")
async def apply_vendor(
    request: Request,
    payload: str = Form(...),
    documents: List[UploadFile] = File(default=[]),
    document_types: str = Form("[]"),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    try:
        data = json.loads(payload)
        app_payload = VendorApplicationPayload(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(400, f"Invalid application data: {e}")

    biz_errors = _validate_payload_business_rules(app_payload)
    if biz_errors:
        raise HTTPException(400, "; ".join(biz_errors))

    # Same company (by NTN) already has a live application or is already an
    # approved vendor — block the resubmission rather than letting it create
    # a second, confusingly-named entry (same company name, different
    # reference code) sitting in a different tab.
    existing_application = db.execute(
        text("""
            SELECT reference_code, status FROM vendor_applications
            WHERE ntn = :ntn AND status IN ('pending', 'needs_info', 'approved')
            ORDER BY submitted_at DESC LIMIT 1
        """),
        {"ntn": app_payload.ntn},
    ).mappings().first()
    if existing_application:
        raise HTTPException(
            400,
            f"An application for this NTN already exists ({existing_application['reference_code']}, "
            f"status: {existing_application['status']}). Contact us if you need to update it.",
        )
    existing_vendor = db.execute(
        text("SELECT id FROM vendors WHERE ntn = :ntn AND status = 'active'"), {"ntn": app_payload.ntn}
    ).first()
    if existing_vendor:
        raise HTTPException(400, "This NTN is already registered as an approved vendor.")

    try:
        doc_types = json.loads(document_types)
    except json.JSONDecodeError:
        doc_types = []

    # Validate every document up front — reject the whole submission on a
    # bad file rather than partially storing (this is one atomic "apply").
    doc_payloads = []
    for i, doc in enumerate(documents):
        content = await doc.read()
        err = _validate_document(doc.filename or f"document_{i}", content)
        if err:
            raise HTTPException(400, err)
        doc_type = doc_types[i] if i < len(doc_types) and doc_types[i] in DOC_TYPES else "other"
        doc_payloads.append((doc, content, doc_type))

    honeypot_triggered = bool(app_payload.website_hp)
    application_id = str(uuid.uuid4())
    email_verify_token = secrets.token_urlsafe(32)

    db.execute(
        text("""
            INSERT INTO vendor_applications (
              id, legal_company_name, trade_name, business_type, ntn, strn, secp_number,
              year_established, employee_range, website, categories,
              contact_name, contact_designation, order_email, email_verify_token,
              email_verify_sent_at, mobile, alternate_phone, address, city, province,
              postal_code, coverage_provinces, coverage_cities,
              lead_time_days, payment_terms, min_order_value, warranty,
              bank_name, bank_account_title, bank_iban, certifications,
              applicant_ip, honeypot_triggered
            ) VALUES (
              :id, :legal_company_name, :trade_name, :business_type, :ntn, :strn, :secp_number,
              :year_established, :employee_range, :website, CAST(:categories AS jsonb),
              :contact_name, :contact_designation, :order_email, :email_verify_token,
              NOW(), :mobile, :alternate_phone, :address, :city, :province,
              :postal_code, CAST(:coverage_provinces AS jsonb), CAST(:coverage_cities AS jsonb),
              :lead_time_days, :payment_terms, :min_order_value, :warranty,
              :bank_name, :bank_account_title, :bank_iban, CAST(:certifications AS jsonb),
              :applicant_ip, :honeypot_triggered
            )
        """),
        {
            "id": application_id,
            "legal_company_name": app_payload.legal_company_name,
            "trade_name": app_payload.trade_name,
            "business_type": app_payload.business_type,
            "ntn": app_payload.ntn,
            "strn": app_payload.strn,
            "secp_number": app_payload.secp_number,
            "year_established": app_payload.year_established,
            "employee_range": app_payload.employee_range,
            "website": app_payload.website,
            "categories": json.dumps(app_payload.categories),
            "contact_name": app_payload.contact_name,
            "contact_designation": app_payload.contact_designation,
            "order_email": app_payload.order_email,
            "email_verify_token": email_verify_token,
            "mobile": app_payload.mobile,
            "alternate_phone": app_payload.alternate_phone,
            "address": app_payload.address,
            "city": app_payload.city,
            "province": app_payload.province,
            "postal_code": app_payload.postal_code,
            "coverage_provinces": json.dumps(app_payload.coverage_provinces),
            "coverage_cities": json.dumps(app_payload.coverage_cities),
            "lead_time_days": app_payload.lead_time_days,
            "payment_terms": app_payload.payment_terms,
            "min_order_value": app_payload.min_order_value,
            "warranty": app_payload.warranty,
            "bank_name": app_payload.bank_name,
            "bank_account_title": app_payload.bank_account_title,
            "bank_iban": app_payload.bank_iban,
            "certifications": json.dumps(app_payload.certifications),
            "applicant_ip": client_ip,
            "honeypot_triggered": honeypot_triggered,
        },
    )

    for item in app_payload.items:
        db.execute(
            text("""
                INSERT INTO vendor_application_items
                  (id, application_id, name, sku, category, description, unit, unit_price, moq, lead_time_days, row_source)
                VALUES (:id, :aid, :name, :sku, :category, :description, :unit, :unit_price, :moq, :lead_time_days, 'manual')
            """),
            {
                "id": str(uuid.uuid4()), "aid": application_id,
                "name": item.name, "sku": item.sku, "category": item.category,
                "description": item.description, "unit": item.unit, "unit_price": item.unit_price,
                "moq": item.moq, "lead_time_days": item.lead_time_days,
            },
        )

    for doc, content, doc_type in doc_payloads:
        ext = os.path.splitext(doc.filename or "")[1].lower()
        stored_filename = secrets.token_hex(24) + ext
        with open(os.path.join(VENDOR_DOCS_DIR, stored_filename), "wb") as f:
            f.write(content)
        db.execute(
            text("""
                INSERT INTO vendor_application_documents
                  (id, application_id, doc_type, original_filename, stored_filename, content_type, size_bytes)
                VALUES (:id, :aid, :doc_type, :orig, :stored, :ctype, :size)
            """),
            {
                "id": str(uuid.uuid4()), "aid": application_id, "doc_type": doc_type,
                "orig": doc.filename, "stored": stored_filename,
                "ctype": doc.content_type, "size": len(content),
            },
        )

    db.commit()

    reference_code = db.execute(
        text("SELECT reference_code FROM vendor_applications WHERE id = :id"), {"id": application_id}
    ).scalar()

    if not honeypot_triggered:
        # Non-fatal: notification/email failures never abort a successful application.
        try:
            send_vendor_application_ack(app_payload.order_email, app_payload.legal_company_name, reference_code)
            send_vendor_email_verification(app_payload.order_email, app_payload.legal_company_name, email_verify_token)
        except Exception as e:
            print(f"[WARN] vendor application ack/verify email failed: {e}")
        try:
            notify(
                db, "vendor_application.submitted", {},
                title=f"New Vendor Application — {app_payload.legal_company_name}",
                body=f"{app_payload.legal_company_name} applied to become a vendor ({reference_code}). "
                     f"Review in Vendor Applications.",
                entity_type="vendor_application", entity_id=application_id, action_path="/vendor-applications",
                metadata={"application_id": application_id, "reference_code": reference_code},
            )
            db.commit()
        except Exception as e:
            print(f"[WARN] vendor application admin notification failed: {e}")

    return {
        "application_id": application_id,
        "reference_code": reference_code,
        "message": f"Application {reference_code} received. We'll email you once it's reviewed.",
    }


# ════════════════════════════════════════════════════════════════════════════
# ADMIN + PROCUREMENT MANAGER — vendor applications (vetting)
# ════════════════════════════════════════════════════════════════════════════

def _application_to_dict(row: dict) -> dict:
    out = dict(row)
    for key in ("categories", "coverage_provinces", "coverage_cities", "certifications", "vetting_checklist"):
        if key in out:
            out[key] = _jsonb(out[key])
    out.pop("bank_name", None)
    out.pop("bank_account_title", None)
    out.pop("bank_iban", None)
    return out


@router.get("/api/vendor-applications", dependencies=[_staff])
def list_vendor_applications(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    filters = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if status:
        filters += " AND status = :status"
        params["status"] = status
    if search:
        filters += " AND (legal_company_name ILIKE :search OR reference_code ILIKE :search OR order_email ILIKE :search)"
        params["search"] = f"%{search}%"

    rows = db.execute(
        text(f"""
            SELECT id, reference_code, legal_company_name, trade_name, business_type,
                   order_email, email_verified, city, province, status,
                   submitted_at, reviewed_at
            FROM vendor_applications {filters}
            ORDER BY submitted_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    counts = db.execute(
        text("SELECT status, COUNT(*) FROM vendor_applications GROUP BY status")
    ).all()

    return {
        "applications": [dict(r) for r in rows],
        "counts": {row[0]: row[1] for row in counts},
    }


@router.get("/api/vendor-applications/{application_id}", dependencies=[_staff])
def get_vendor_application(application_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT * FROM vendor_applications WHERE id = :id"), {"id": application_id}
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Application not found")

    items = db.execute(
        text("SELECT * FROM vendor_application_items WHERE application_id = :id ORDER BY created_at"),
        {"id": application_id},
    ).mappings().all()
    documents = db.execute(
        text("""
            SELECT id, doc_type, original_filename, content_type, size_bytes, uploaded_at
            FROM vendor_application_documents WHERE application_id = :id ORDER BY uploaded_at
        """),
        {"id": application_id},
    ).mappings().all()

    out = _application_to_dict(dict(row))
    # Vetting view needs bank details for verification — add them back here only.
    out["bank_name"] = row["bank_name"]
    out["bank_account_title"] = row["bank_account_title"]
    out["bank_iban"] = row["bank_iban"]
    out["items"] = [dict(i) for i in items]
    out["documents"] = [dict(d) for d in documents]
    return out


@router.get("/api/vendor-applications/{application_id}/documents/{document_id}")
def download_vendor_application_document(
    application_id: str, document_id: str,
    user: dict = Depends(require_role(ROLE_PROCUREMENT_MANAGER)),
    db: Session = Depends(get_db),
):
    doc = db.execute(
        text("""
            SELECT stored_filename, original_filename, content_type
            FROM vendor_application_documents
            WHERE id = :did AND application_id = :aid
        """),
        {"did": document_id, "aid": application_id},
    ).mappings().first()
    if not doc:
        raise HTTPException(404, "Document not found")
    path = os.path.join(VENDOR_DOCS_DIR, doc["stored_filename"])
    if not os.path.isfile(path):
        raise HTTPException(404, "Document file missing on disk")
    with open(path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type=doc["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{doc["original_filename"] or doc["stored_filename"]}"'},
    )


class ChecklistUpdate(BaseModel):
    checklist: dict


@router.post("/api/vendor-applications/{application_id}/checklist", dependencies=[_staff])
def update_vetting_checklist(application_id: str, req: ChecklistUpdate, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT id FROM vendor_applications WHERE id = :id"), {"id": application_id}).first()
    if not row:
        raise HTTPException(404, "Application not found")
    db.execute(
        text("UPDATE vendor_applications SET vetting_checklist = CAST(:c AS jsonb), updated_at = NOW() WHERE id = :id"),
        {"c": json.dumps(req.checklist), "id": application_id},
    )
    db.commit()
    return {"message": "Checklist updated"}


@router.post("/api/vendor-applications/{application_id}/approve", dependencies=[_staff])
def approve_vendor_application(
    application_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.execute(
        text("SELECT * FROM vendor_applications WHERE id = :id"), {"id": application_id}
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Application not found")
    if row["status"] not in ("pending", "needs_info"):
        raise HTTPException(400, f"Application is not pending (status: {row['status']})")

    items = db.execute(
        text("SELECT * FROM vendor_application_items WHERE application_id = :id"), {"id": application_id}
    ).mappings().all()

    try:
        vendor_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO vendors (
                  id, name, email, phone, country, is_active, status, order_email,
                  trade_name, business_type, ntn, strn, secp_number, year_established,
                  employee_range, website, categories, contact_name, contact_designation,
                  mobile, alternate_phone, address, city, province, postal_code,
                  coverage_provinces, coverage_cities, lead_time_days, payment_terms,
                  min_order_value, warranty, bank_name, bank_account_title, bank_iban,
                  certifications, email_verified, application_id, approved_by
                ) VALUES (
                  :id, :name, :email, :phone, 'Pakistan', TRUE, 'active', :order_email,
                  :trade_name, :business_type, :ntn, :strn, :secp_number, :year_established,
                  :employee_range, :website, CAST(:categories AS jsonb), :contact_name, :contact_designation,
                  :mobile, :alternate_phone, :address, :city, :province, :postal_code,
                  CAST(:coverage_provinces AS jsonb), CAST(:coverage_cities AS jsonb), :lead_time_days, :payment_terms,
                  :min_order_value, :warranty, :bank_name, :bank_account_title, :bank_iban,
                  CAST(:certifications AS jsonb), :email_verified, :application_id, :approved_by
                )
            """),
            {
                "id": vendor_id, "name": row["legal_company_name"], "email": row["order_email"],
                "phone": row["mobile"], "order_email": row["order_email"],
                "trade_name": row["trade_name"], "business_type": row["business_type"],
                "ntn": row["ntn"], "strn": row["strn"], "secp_number": row["secp_number"],
                "year_established": row["year_established"], "employee_range": row["employee_range"],
                "website": row["website"], "categories": json.dumps(_jsonb(row["categories"])),
                "contact_name": row["contact_name"], "contact_designation": row["contact_designation"],
                "mobile": row["mobile"], "alternate_phone": row["alternate_phone"],
                "address": row["address"], "city": row["city"], "province": row["province"],
                "postal_code": row["postal_code"],
                "coverage_provinces": json.dumps(_jsonb(row["coverage_provinces"])),
                "coverage_cities": json.dumps(_jsonb(row["coverage_cities"])),
                "lead_time_days": row["lead_time_days"], "payment_terms": row["payment_terms"],
                "min_order_value": row["min_order_value"], "warranty": row["warranty"],
                "bank_name": row["bank_name"], "bank_account_title": row["bank_account_title"],
                "bank_iban": row["bank_iban"], "certifications": json.dumps(_jsonb(row["certifications"])),
                "email_verified": row["email_verified"], "application_id": application_id,
                "approved_by": user["id"],
            },
        )

        for item in items:
            db.execute(
                text("""
                    INSERT INTO vendor_items (id, vendor_id, name, sku, category, description, unit, unit_price, moq, lead_time_days)
                    VALUES (:id, :vid, :name, :sku, :category, :description, :unit, :unit_price, :moq, :lead_time_days)
                """),
                {
                    "id": str(uuid.uuid4()), "vid": vendor_id,
                    "name": item["name"], "sku": item["sku"], "category": item["category"],
                    "description": item["description"], "unit": item["unit"],
                    "unit_price": item["unit_price"], "moq": item["moq"],
                    "lead_time_days": item["lead_time_days"],
                },
            )

        db.execute(
            text("""
                UPDATE vendor_applications SET
                  status = 'approved', reviewed_by = :uid, reviewed_at = NOW(),
                  approved_vendor_id = :vid, updated_at = NOW()
                WHERE id = :id
            """),
            {"uid": user["id"], "vid": vendor_id, "id": application_id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Approval failed, no changes were made: {e}")

    try:
        send_vendor_approved_email(row["order_email"], row["legal_company_name"], row["order_email"])
    except Exception as e:
        print(f"[WARN] vendor approval email failed: {e}")
    try:
        auto_resolve(db, "vendor_application", application_id)
        notify(
            db, "vendor_application.approved", {"actor_user_id": user["id"]},
            title=f"Vendor Approved — {row['legal_company_name']}",
            body=f"You approved {row['legal_company_name']} ({row['reference_code']}). "
                 f"They now appear in the approved vendor catalogue.",
            entity_type="vendor", entity_id=vendor_id, action_path="/vendor-catalogue",
            metadata={"vendor_id": vendor_id},
        )
        db.commit()
    except Exception as e:
        print(f"[WARN] vendor approval notification failed: {e}")

    return {"message": f"{row['legal_company_name']} approved", "vendor_id": vendor_id}


class RejectApplicationRequest(BaseModel):
    reason: str


@router.post("/api/vendor-applications/{application_id}/reject", dependencies=[_staff])
def reject_vendor_application(
    application_id: str, req: RejectApplicationRequest,
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not req.reason or not req.reason.strip():
        raise HTTPException(400, "A rejection reason is required")

    row = db.execute(
        text("SELECT legal_company_name, order_email, status FROM vendor_applications WHERE id = :id"),
        {"id": application_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Application not found")
    if row["status"] not in ("pending", "needs_info"):
        raise HTTPException(400, f"Application is not pending (status: {row['status']})")

    db.execute(
        text("""
            UPDATE vendor_applications SET
              status = 'rejected', reviewed_by = :uid, reviewed_at = NOW(),
              rejection_reason = :reason, updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": user["id"], "reason": req.reason, "id": application_id},
    )
    auto_resolve(db, "vendor_application", application_id)
    db.commit()

    try:
        send_vendor_rejected_email(row["order_email"], row["legal_company_name"], req.reason)
    except Exception as e:
        print(f"[WARN] vendor rejection email failed: {e}")

    return {"message": f"{row['legal_company_name']} rejected"}


class RequestInfoRequest(BaseModel):
    note: str


@router.post("/api/vendor-applications/{application_id}/request-info", dependencies=[_staff])
def request_vendor_info(
    application_id: str, req: RequestInfoRequest,
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not req.note or not req.note.strip():
        raise HTTPException(400, "A note describing what's needed is required")

    row = db.execute(
        text("SELECT legal_company_name, order_email, status FROM vendor_applications WHERE id = :id"),
        {"id": application_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Application not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Application is not pending (status: {row['status']})")

    db.execute(
        text("""
            UPDATE vendor_applications SET
              status = 'needs_info', reviewed_by = :uid, reviewed_at = NOW(),
              admin_notes = :note, updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": user["id"], "note": req.note, "id": application_id},
    )
    db.commit()

    try:
        send_vendor_needs_info_email(row["order_email"], row["legal_company_name"], req.note)
    except Exception as e:
        print(f"[WARN] vendor needs-info email failed: {e}")

    return {"message": f"Requested more information from {row['legal_company_name']}"}


# ════════════════════════════════════════════════════════════════════════════
# ADMIN + PROCUREMENT MANAGER — approved vendor catalogue
# ════════════════════════════════════════════════════════════════════════════

def _vendor_to_dict(row: dict) -> dict:
    out = dict(row)
    for key in ("categories", "coverage_provinces", "coverage_cities", "certifications"):
        if key in out:
            out[key] = _jsonb(out[key])
    out.pop("bank_name", None)
    out.pop("bank_account_title", None)
    out.pop("bank_iban", None)
    return out


@router.get("/api/vendors", dependencies=[_staff])
def list_vendors(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Approved (active) vendors only — enforced here, not just in the UI."""
    filters = "WHERE v.status = 'active'"
    params: dict = {"limit": limit, "offset": offset}
    if search:
        filters += """ AND (
            v.name ILIKE :search OR
            EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.vendor_id = v.id AND vi.name ILIKE :search)
        )"""
        params["search"] = f"%{search}%"
    if category:
        filters += " AND EXISTS (SELECT 1 FROM vendor_items vi WHERE vi.vendor_id = v.id AND vi.category = :category)"
        params["category"] = category

    rows = db.execute(
        text(f"""
            SELECT v.*, COUNT(vi.id) AS item_count
            FROM vendors v
            LEFT JOIN vendor_items vi ON vi.vendor_id = v.id AND vi.is_active = TRUE
            {filters}
            GROUP BY v.id
            ORDER BY v.name ASC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    return {"vendors": [_vendor_to_dict(dict(r)) for r in rows]}


@router.get("/api/vendors/{vendor_id}", dependencies=[_staff])
def get_vendor(vendor_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT * FROM vendors WHERE id = :id AND status = 'active'"), {"id": vendor_id}
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Vendor not found")
    return _vendor_to_dict(dict(row))


@router.get("/api/vendors/{vendor_id}/items", dependencies=[_staff])
def get_vendor_items(vendor_id: str, db: Session = Depends(get_db)):
    vendor = db.execute(
        text("SELECT id FROM vendors WHERE id = :id AND status = 'active'"), {"id": vendor_id}
    ).first()
    if not vendor:
        raise HTTPException(404, "Vendor not found")
    items = db.execute(
        text("SELECT * FROM vendor_items WHERE vendor_id = :id AND is_active = TRUE ORDER BY name"),
        {"id": vendor_id},
    ).mappings().all()
    return {"items": [dict(i) for i in items]}
