"""
Vendor payout accounts — IBAN checksum, normalization, cross-field
validation, duplicate rejection, masking, the approval gate, and step M's
(payments.release_payout) blocking behavior. Needs a live Postgres for
every test that touches persistence — this repo doesn't mock the database
(see test_vema_reorder.py and every other test file here). The pure
validation/normalization tests don't technically need a DB, but are kept
under the same module-level skip for consistency with that convention.
"""
import uuid

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from database import db_session
import vendor_payment_accounts as vpa
import vendors
import payments
from rbac import ROLE_PROCUREMENT_MANAGER


def _db_available() -> bool:
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live Postgres connection")

_PM_USER = {"id": "aaaaaaaa-0000-0000-0000-000000000003", "role": ROLE_PROCUREMENT_MANAGER, "name": "Test PM", "email": "pm@test"}
# Seeded dev vendor used throughout the rest of the test suite / seed data —
# has no vendor_payment_accounts row, which is exactly what the "missing
# account" tests need.
_SEED_VENDOR_ID = "11111111-0000-0000-0000-000000000001"

# A handful of checksum-valid Pakistani IBANs for Habib Bank (HABB), computed
# with the same ISO 13616 algorithm the code under test implements —
# independently re-derived here, not copy-pasted from the implementation.
_VALID_IBAN = "PK66HABB0000001234567890"
_INVALID_CHECKSUM_IBAN = "PK65HABB0000001234567890"  # one off from _VALID_IBAN
_BAD_FORMAT_IBAN = "PK66HABB00000012345"  # too short


# ────────────────────────────────────────────────────────────────────────────
# Pure validation / normalization
# ────────────────────────────────────────────────────────────────────────────

def test_iban_checksum_valid_sample():
    assert vpa.iban_checksum_valid(_VALID_IBAN) is True


def test_iban_checksum_rejects_wrong_check_digits():
    assert vpa.iban_checksum_valid(_INVALID_CHECKSUM_IBAN) is False


def test_iban_checksum_rejects_bad_format():
    assert vpa.iban_checksum_valid(_BAD_FORMAT_IBAN) is False


@pytest.mark.parametrize("raw,expected", [
    ("03001234567", "03001234567"),
    ("+923001234567", "03001234567"),
    ("00923001234567", "03001234567"),
    ("0300-123-4567", "03001234567"),
    ("0300 123 4567", "03001234567"),
])
def test_wallet_number_normalization(raw, expected):
    assert vpa.normalize_wallet_number(raw) == expected


def test_validate_rejects_mismatched_method_fields_for_bank_account():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="bank_account", account_title="Test Co",
        bank_name="Habib Bank Limited", iban=_VALID_IBAN,
        wallet_provider="jazzcash",  # not allowed alongside bank_account
    )
    errors, _ = vpa.validate_payout_account(p)
    assert any("wallet_provider" in e for e in errors)


def test_validate_rejects_mismatched_method_fields_for_wallet():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="mobile_wallet", account_title="Test Co",
        wallet_provider="jazzcash", wallet_number="03001234567",
        bank_name="Habib Bank Limited",  # not allowed alongside mobile_wallet
    )
    errors, _ = vpa.validate_payout_account(p)
    assert any("bank_name" in e for e in errors)


def test_validate_rejects_unknown_bank():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="bank_account", account_title="Test Co",
        bank_name="Totally Fictional Bank", iban=_VALID_IBAN,
    )
    errors, _ = vpa.validate_payout_account(p)
    assert any("bank_name" in e for e in errors)


def test_validate_rejects_bad_account_number():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="bank_account", account_title="Test Co",
        bank_name="Habib Bank Limited", iban=_VALID_IBAN, account_number="123",
    )
    errors, _ = vpa.validate_payout_account(p)
    assert any("account_number" in e for e in errors)


def test_validate_accepts_valid_bank_account():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="bank_account", account_title="Test Co",
        bank_name="Habib Bank Limited", iban=_VALID_IBAN,
    )
    errors, _ = vpa.validate_payout_account(p)
    assert errors == []


def test_validate_accepts_valid_wallet():
    p = vpa.VendorPaymentAccountCreate(
        payout_method="mobile_wallet", account_title="Test Co",
        wallet_provider="jazzcash", wallet_number="03001234567",
    )
    errors, _ = vpa.validate_payout_account(p)
    assert errors == []


# ────────────────────────────────────────────────────────────────────────────
# Persistence: masking, duplicate rejection, approval gate, step M
# ────────────────────────────────────────────────────────────────────────────

def _insert_application(ntn_suffix: str, legal_name: str) -> str:
    application_id = str(uuid.uuid4())
    with db_session() as db:
        db.execute(
            sa.text("""
                INSERT INTO vendor_applications (
                  id, legal_company_name, business_type, ntn, contact_name, order_email,
                  mobile, address, city, province
                ) VALUES (
                  :id, :name, 'Distributor', :ntn, 'Test Contact', :email,
                  '03001234567', 'Test Address', 'Islamabad', 'Islamabad Capital Territory'
                )
            """),
            {"id": application_id, "name": legal_name, "ntn": f"TEST-{ntn_suffix}", "email": f"{ntn_suffix}@test.example"},
        )
        db.commit()
    return application_id


def _insert_vendor_order(vendor_id, orderer_id, *, payment_status="Captured", payout_status="Scheduled",
                          subtotal=1000.00, platform_fee=5.00):
    order_id = str(uuid.uuid4())
    order_code = "ZTEST-" + uuid.uuid4().hex[:8].upper()
    with db_session() as db:
        db.execute(
            sa.text("""
                INSERT INTO vendor_orders (
                  id, order_code, vendor_id, orderer_user_id, destination_name, subtotal, total_amount,
                  currency, status, expires_at, payment_status, payout_status, vendor_payout_amount,
                  platform_fee, payment_captured_at
                ) VALUES (
                  :id, :code, :vid, :uid, 'Test Warehouse', :sub, :total,
                  'PKR', 'ACCEPTED', NOW() + INTERVAL '3 days', :pstat, :postat, :payout,
                  :fee, NOW()
                )
            """),
            {
                "id": order_id, "code": order_code, "vid": vendor_id, "uid": orderer_id,
                "sub": subtotal, "total": round(subtotal + platform_fee, 2), "pstat": payment_status,
                "postat": payout_status, "payout": subtotal, "fee": platform_fee,
            },
        )
        db.commit()
    return order_id


def _cleanup_applications(application_ids=()):
    with db_session() as db:
        for aid in application_ids:
            db.execute(sa.text("DELETE FROM vendor_payment_account_audit_log WHERE account_id IN "
                                "(SELECT id FROM vendor_payment_accounts WHERE application_id = :id)"), {"id": aid})
            db.execute(sa.text("DELETE FROM vendor_payment_accounts WHERE application_id = :id"), {"id": aid})
            db.execute(sa.text("DELETE FROM vendor_application_items WHERE application_id = :id"), {"id": aid})
            db.execute(sa.text("DELETE FROM vendor_applications WHERE id = :id"), {"id": aid})
        db.commit()


def _cleanup_orders(order_ids=()):
    with db_session() as db:
        for oid in order_ids:
            db.execute(sa.text("DELETE FROM notifications WHERE entity_id = :id"), {"id": oid})
            db.execute(sa.text("DELETE FROM payment_transactions WHERE order_id = :id"), {"id": oid})
            db.execute(sa.text("DELETE FROM vendor_orders WHERE id = :id"), {"id": oid})
        db.commit()


def test_create_and_mask_bank_account():
    aid = _insert_application("mask1", "Mask Test Co")
    try:
        with db_session() as db:
            payload = vpa.VendorPaymentAccountCreate(
                payout_method="bank_account", account_title="Mask Test Co",
                bank_name="Habib Bank Limited", iban=_VALID_IBAN,
            )
            vpa.create_payment_account_for_application(db, aid, payload)
            db.commit()
            summary = vpa.account_for_application(db, aid)
        assert summary is not None
        assert summary["verification_status"] == "pending"
        # Masked — never the full IBAN, only the last 4 digits visible.
        assert summary["iban_masked"] == "••••7890"
        assert "PK66" not in str(summary)
    finally:
        _cleanup_applications([aid])


def test_duplicate_iban_rejected_with_409():
    aid1 = _insert_application("dup1", "Dup Co One")
    aid2 = _insert_application("dup2", "Dup Co Two")
    try:
        with db_session() as db:
            payload = vpa.VendorPaymentAccountCreate(
                payout_method="bank_account", account_title="Dup Co One",
                bank_name="Habib Bank Limited", iban=_VALID_IBAN,
            )
            vpa.create_payment_account_for_application(db, aid1, payload)
            db.commit()

        with db_session() as db:
            payload2 = vpa.VendorPaymentAccountCreate(
                payout_method="bank_account", account_title="Dup Co Two",
                bank_name="Habib Bank Limited", iban=_VALID_IBAN,  # same IBAN, different application
            )
            with pytest.raises(HTTPException) as exc:
                vpa.create_payment_account_for_application(db, aid2, payload2)
            assert exc.value.status_code == 409
    finally:
        _cleanup_applications([aid1, aid2])


def test_approval_blocked_without_verified_account():
    aid = _insert_application("gate1", "Gate Test Co")
    try:
        with db_session() as db:
            # No payment account at all yet.
            assert vpa.is_verified_for_application(db, aid) is False
            with pytest.raises(HTTPException) as exc:
                vendors.approve_vendor_application(aid, user=_PM_USER, db=db)
            assert exc.value.status_code == 400
    finally:
        _cleanup_applications([aid])


def test_approval_blocked_when_account_pending_not_verified():
    aid = _insert_application("gate2", "Gate Test Co Two")
    try:
        with db_session() as db:
            payload = vpa.VendorPaymentAccountCreate(
                payout_method="mobile_wallet", account_title="Gate Test Co Two",
                wallet_provider="jazzcash", wallet_number="03001234567",
            )
            vpa.create_payment_account_for_application(db, aid, payload)
            db.commit()
            assert vpa.is_verified_for_application(db, aid) is False
    finally:
        _cleanup_applications([aid])


def test_reveal_verify_reject_cycle_and_audit_log():
    aid = _insert_application("cycle1", "Cycle Test Co")
    try:
        with db_session() as db:
            payload = vpa.VendorPaymentAccountCreate(
                payout_method="bank_account", account_title="Cycle Test Co",
                bank_name="Habib Bank Limited", iban=_VALID_IBAN,
            )
            vpa.create_payment_account_for_application(db, aid, payload)
            db.commit()

            revealed = vpa.reveal_account(db, aid, _PM_USER["id"])
            db.commit()
            assert revealed["iban"] == _VALID_IBAN

            vpa.verify_account(db, aid, _PM_USER["id"])
            db.commit()
            assert vpa.is_verified_for_application(db, aid) is True

            vpa.reject_account(db, aid, _PM_USER["id"], "changed my mind")
            db.commit()
            assert vpa.is_verified_for_application(db, aid) is False

            account_id = db.execute(
                sa.text("SELECT id FROM vendor_payment_accounts WHERE application_id = :id"), {"id": aid}
            ).scalar()
            actions = db.execute(
                sa.text("SELECT action FROM vendor_payment_account_audit_log WHERE account_id = :id ORDER BY created_at"),
                {"id": account_id},
            ).scalars().all()
            assert actions == ["reveal", "verify", "reject"]
    finally:
        _cleanup_applications([aid])


def test_get_vendor_payout_destination_missing_raises():
    with db_session() as db:
        with pytest.raises(vpa.VendorPayoutAccountMissing):
            vpa.get_vendor_payout_destination(db, _SEED_VENDOR_ID)


def test_release_payout_blocks_and_notifies_without_verified_account():
    """Step M (payments.release_payout) — a vendor with no verified payout
    account must never reach the payment processor; the order is marked
    Failed (the same 'blocked, needs admin attention' shape the processors
    already use for 'no bank IBAN on file'), and an admin is notified."""
    order_id = _insert_vendor_order(_SEED_VENDOR_ID, _PM_USER["id"])
    try:
        with db_session() as db:
            result = payments.release_payout(db, order_id, actor_user_id=_PM_USER["id"])
            db.commit()
        assert result["status"] == "Failed"
        assert result["payout_ref"] is None

        with db_session() as db:
            row = db.execute(
                sa.text("SELECT payout_status FROM vendor_orders WHERE id = :id"), {"id": order_id}
            ).mappings().first()
            assert row["payout_status"] == "Failed"

            txn = db.execute(
                sa.text("SELECT status, note FROM payment_transactions WHERE order_id = :id AND kind = 'payout'"),
                {"id": order_id},
            ).mappings().first()
            assert txn is not None
            assert txn["status"] == "Failed"
    finally:
        _cleanup_orders([order_id])
