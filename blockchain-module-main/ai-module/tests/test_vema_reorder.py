"""
VEMA Auto-Reorder — threshold/dedup/quantity/vendor-ranking/approval tests.
Needs a live Postgres (real scan_and_create_requests()/approve/reject
calls — this repo doesn't mock the database, see conftest.py and every
other test file). The one exception, noted at that test specifically, is a
single targeted patch of one internal function to simulate a mid-scan
failure — not a database mock.
"""
import uuid
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from database import db_session
import vema_reorder_service as vema
from vema_reorder_router import approve_vema_request, reject_vema_request, ApproveRequestBody, RejectRequestBody
from rbac import require_role, ROLE_PROCUREMENT_MANAGER, ROLE_ADMIN, ROLE_CUSTOMER_REP


def _db_available() -> bool:
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live Postgres connection")

_PM_USER = {"id": "aaaaaaaa-0000-0000-0000-000000000003", "role": ROLE_PROCUREMENT_MANAGER, "name": "Test PM", "email": "pm@test"}
# Seeded dev vendor used throughout the rest of the test suite / seed data.
_SEED_VENDOR_ID = "11111111-0000-0000-0000-000000000001"


def _insert_item(item_id, *, min_threshold=100, critical_threshold=20, current_stock=50,
                  category="TestCategory", vendor_id=None, unit_price=500.00, max_stock_level=None):
    with db_session() as db:
        db.execute(
            sa.text("""
                INSERT INTO inventory_items (
                  item_id, name, category, unit, min_threshold, critical_threshold,
                  current_stock, daily_consumption, reorder_quantity, vendor_id, status,
                  unit_price, max_stock_level
                ) VALUES (
                  :id, :name, :cat, 'unit', :mn, :cr, :stock, 1, 10, :vid, 'OK', :price, :par
                )
            """),
            {
                "id": item_id, "name": f"Test {item_id}", "cat": category, "mn": min_threshold,
                "cr": critical_threshold, "stock": current_stock, "vid": vendor_id, "price": unit_price,
                "par": max_stock_level,
            },
        )
        db.commit()


def _insert_vendor_item(vendor_id, category, unit_price, lead_time_days=10, moq=None):
    item_row_id = str(uuid.uuid4())
    with db_session() as db:
        db.execute(
            sa.text("""
                INSERT INTO vendor_items (id, vendor_id, name, category, unit, unit_price, lead_time_days, moq, is_active)
                VALUES (:id, :vid, 'Test Catalogue Item', :cat, 'unit', :price, :lt, :moq, TRUE)
            """),
            {"id": item_row_id, "vid": vendor_id, "cat": category, "price": unit_price, "lt": lead_time_days, "moq": moq},
        )
        db.commit()
    return item_row_id


def _cleanup(item_ids=(), vendor_item_ids=(), order_ids=()):
    with db_session() as db:
        # vema_reorder_requests.resulting_order_id references
        # procurement_orders -- must be cleared before an order can be
        # deleted, or the FK rejects the DELETE.
        for iid in item_ids:
            db.execute(sa.text("DELETE FROM vema_reorder_audit_log WHERE request_id IN (SELECT id FROM vema_reorder_requests WHERE item_id = :id)"), {"id": iid})
            db.execute(sa.text("DELETE FROM vema_reorder_requests WHERE item_id = :id"), {"id": iid})
        for oid in order_ids:
            db.execute(sa.text("DELETE FROM contract_audit_log WHERE order_id = :id"), {"id": oid})
            db.execute(sa.text("DELETE FROM vendor_comm_log WHERE order_id = :id"), {"id": oid})
            db.execute(sa.text("DELETE FROM procurement_orders WHERE id = :id"), {"id": oid})
        for iid in item_ids:
            db.execute(sa.text("DELETE FROM procurement_orders WHERE item_id = :id"), {"id": iid})
            db.execute(sa.text("DELETE FROM inventory_items WHERE item_id = :id"), {"id": iid})
        for vid in vendor_item_ids:
            db.execute(sa.text("DELETE FROM vendor_items WHERE id = :id"), {"id": vid})
        db.commit()


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------

def test_threshold_boundary_21pct_does_not_trigger():
    item_id = "ZTEST-THR-21"
    # par = min_threshold*2 (no max_stock_level set) = 200; 20% of 200 = 40.
    # 21% of 200 = 42 -> should NOT trigger.
    _insert_item(item_id, min_threshold=100, current_stock=42)
    try:
        with db_session() as db:
            result = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert result is None
    finally:
        _cleanup(item_ids=[item_id])


def test_threshold_boundary_exactly_20pct_triggers():
    item_id = "ZTEST-THR-20"
    _insert_item(item_id, min_threshold=100, current_stock=40)  # exactly 20% of par=200
    try:
        with db_session() as db:
            result = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert result is not None
    finally:
        _cleanup(item_ids=[item_id])


def test_threshold_boundary_0pct_triggers():
    item_id = "ZTEST-THR-00"
    _insert_item(item_id, min_threshold=100, current_stock=0)
    try:
        with db_session() as db:
            result = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert result is not None
    finally:
        _cleanup(item_ids=[item_id])


# ---------------------------------------------------------------------------
# Dedup / cooldown
# ---------------------------------------------------------------------------

def test_dedup_no_second_request_while_one_is_pending():
    item_id = "ZTEST-DEDUP-PENDING"
    _insert_item(item_id, current_stock=5)
    try:
        with db_session() as db:
            first = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
            assert first is not None
            second = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert second is None
    finally:
        _cleanup(item_ids=[item_id])


def test_dedup_rejected_item_is_skipped_during_cooldown():
    item_id = "ZTEST-DEDUP-COOLDOWN"
    _insert_item(item_id, current_stock=5)
    try:
        with db_session() as db:
            first = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
            db.execute(
                sa.text("UPDATE vema_reorder_requests SET status = 'rejected', decided_at = NOW() WHERE id = :id"),
                {"id": first["request_id"]},
            )
            db.commit()

            retried = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert retried is None  # still cooling down (default 24h)
    finally:
        _cleanup(item_ids=[item_id])


def test_dedup_rejected_item_retriggers_after_cooldown_expires():
    item_id = "ZTEST-DEDUP-EXPIRED"
    _insert_item(item_id, current_stock=5)
    try:
        with db_session() as db:
            first = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
            # Backdate the rejection past the cooldown window instead of
            # waiting real hours — same "make the clock claim have already
            # passed" approach used for TIMESTAMPTZ elsewhere in this suite.
            db.execute(
                sa.text("""
                    UPDATE vema_reorder_requests
                    SET status = 'rejected', decided_at = NOW() - INTERVAL '25 hours'
                    WHERE id = :id
                """),
                {"id": first["request_id"]},
            )
            db.commit()

            retried = vema._create_request_for_item(db, dict(
                db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first()
            ))
        assert retried is not None
    finally:
        _cleanup(item_ids=[item_id])


# ---------------------------------------------------------------------------
# Quantity calculation
# ---------------------------------------------------------------------------

def test_quantity_accounts_for_inbound_stock():
    item_id = "ZTEST-QTY-INBOUND"
    _insert_item(item_id, min_threshold=100, current_stock=10)  # par=200
    order_id = str(uuid.uuid4())
    try:
        with db_session() as db:
            db.execute(
                sa.text("""
                    INSERT INTO procurement_orders (id, order_code, item_id, vendor_id, quantity, unit, trigger_type, stage, tracking_events, created_at, updated_at)
                    VALUES (:id, :code, :item_id, :vid, 150, 'unit', 'Manual', 'Vendor Notified', '[]'::jsonb, NOW(), NOW())
                """),
                {"id": order_id, "code": "ZTEST-ORD", "item_id": item_id, "vid": _SEED_VENDOR_ID},
            )
            db.commit()
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            par = vema._resolve_par_level(item)
            qty_without_inbound = vema._compute_quantity(db, {**item, "item_id": "ZTEST-NONEXISTENT"}, par, None)
            qty_with_inbound = vema._compute_quantity(db, item, par, None)
        # The same shortfall, minus the 150 already inbound for the real item.
        assert qty_with_inbound < qty_without_inbound
    finally:
        _cleanup(item_ids=[item_id], order_ids=[order_id])


def test_quantity_rounds_up_to_vendor_moq():
    item_id = "ZTEST-QTY-MOQ"
    _insert_item(item_id, min_threshold=10, current_stock=8)  # tiny shortfall
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            par = vema._resolve_par_level(item)
            qty = vema._compute_quantity(db, item, par, vendor_moq=1000)
        assert qty == 1000
    finally:
        _cleanup(item_ids=[item_id])


def test_quantity_skips_forecast_term_when_prediction_unavailable():
    item_id = "ZTEST-QTY-NOFORECAST"
    _insert_item(item_id, min_threshold=100, current_stock=10)
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
        with patch("inventory_v2.calculate_prediction", side_effect=RuntimeError("model unavailable")):
            forecast = vema._forecast_demand(item)
        assert forecast == 0.0
    finally:
        _cleanup(item_ids=[item_id])


# ---------------------------------------------------------------------------
# Vendor ranking
# ---------------------------------------------------------------------------

def test_vendor_ranking_only_considers_active_vendors():
    item_id = "ZTEST-VEND-INACTIVE"
    _insert_item(item_id, category="ZTestCategoryVendor")
    inactive_vendor_id = str(uuid.uuid4())
    vi_id = None
    try:
        with db_session() as db:
            db.execute(
                sa.text("""
                    INSERT INTO vendors (id, name, email, country, status)
                    VALUES (:id, 'Inactive Test Vendor', 'inactive@test.example', 'Pakistan', 'suspended')
                """),
                {"id": inactive_vendor_id},
            )
            db.commit()
        vi_id = _insert_vendor_item(inactive_vendor_id, "ZTestCategoryVendor", 999.00)

        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            best, alts, breakdown = vema._rank_vendors(db, item)
        assert best is None  # the only candidate is suspended, so none qualify
    finally:
        _cleanup(item_ids=[item_id], vendor_item_ids=[vi_id] if vi_id else [])
        with db_session() as db:
            db.execute(sa.text("DELETE FROM vendors WHERE id = :id"), {"id": inactive_vendor_id})
            db.commit()


def test_no_eligible_vendor_creates_request_with_null_vendor_and_approval_needs_422():
    item_id = "ZTEST-VEND-NONE"
    _insert_item(item_id, category="ZTestCategoryNoMatch", current_stock=5)
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            result = vema._create_request_for_item(db, item)
        assert result is not None

        with db_session() as db:
            row = dict(db.execute(sa.text("SELECT * FROM vema_reorder_requests WHERE id = :id"), {"id": result["request_id"]}).mappings().first())
        assert row["vendor_id"] is None

        with db_session() as db:
            with pytest.raises(Exception) as exc_info:
                approve_vema_request(result["request_id"], ApproveRequestBody(), user=_PM_USER, db=db)
            assert getattr(exc_info.value, "status_code", None) == 422
    finally:
        _cleanup(item_ids=[item_id])


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------

def test_approve_creates_order_and_logs_exactly_one_vendor_email_attempt():
    item_id = "ZTEST-APPROVE-OK"
    _insert_item(item_id, category="ZTestCategoryApprove", current_stock=5, vendor_id=_SEED_VENDOR_ID, unit_price=500.0)
    order_id = None
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            result = vema._create_request_for_item(db, item)
        assert result is not None

        with db_session() as db:
            approve_result = approve_vema_request(result["request_id"], ApproveRequestBody(), user=_PM_USER, db=db)
        order_id = approve_result["order_id"]

        with db_session() as db:
            req = dict(db.execute(sa.text("SELECT * FROM vema_reorder_requests WHERE id = :id"), {"id": result["request_id"]}).mappings().first())
            comm_log_count = db.execute(
                sa.text("SELECT COUNT(*) FROM vendor_comm_log WHERE order_id = :id AND channel = 'n8n-email'"),
                {"id": order_id},
            ).scalar()
            order = dict(db.execute(sa.text("SELECT * FROM procurement_orders WHERE id = :id"), {"id": order_id}).mappings().first())

        assert req["status"] == "approved"
        assert str(req["resulting_order_id"]) == order_id
        assert comm_log_count == 1  # the email workflow was invoked exactly once
        assert order["pm_approval_status"] == "Approved"
    finally:
        _cleanup(item_ids=[item_id], order_ids=[order_id] if order_id else [])


def test_double_approve_returns_409():
    item_id = "ZTEST-APPROVE-TWICE"
    _insert_item(item_id, category="ZTestCategoryApprove2", current_stock=5, vendor_id=_SEED_VENDOR_ID, unit_price=500.0)
    order_id = None
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            result = vema._create_request_for_item(db, item)

        with db_session() as db:
            approve_result = approve_vema_request(result["request_id"], ApproveRequestBody(), user=_PM_USER, db=db)
        order_id = approve_result["order_id"]

        with db_session() as db:
            with pytest.raises(Exception) as exc_info:
                approve_vema_request(result["request_id"], ApproveRequestBody(), user=_PM_USER, db=db)
            assert getattr(exc_info.value, "status_code", None) == 409
    finally:
        _cleanup(item_ids=[item_id], order_ids=[order_id] if order_id else [])


def test_reject_creates_no_order_and_sends_no_email():
    item_id = "ZTEST-REJECT"
    _insert_item(item_id, category="ZTestCategoryReject", current_stock=5, vendor_id=_SEED_VENDOR_ID, unit_price=500.0)
    try:
        with db_session() as db:
            item = dict(db.execute(sa.text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": item_id}).mappings().first())
            result = vema._create_request_for_item(db, item)

        with db_session() as db:
            reject_vema_request(result["request_id"], RejectRequestBody(reason="test: not needed"), user=_PM_USER, db=db)

        with db_session() as db:
            req = dict(db.execute(sa.text("SELECT * FROM vema_reorder_requests WHERE id = :id"), {"id": result["request_id"]}).mappings().first())
            order_count = db.execute(sa.text("SELECT COUNT(*) FROM procurement_orders WHERE item_id = :id"), {"id": item_id}).scalar()

        assert req["status"] == "rejected"
        assert req["resulting_order_id"] is None
        assert order_count == 0
    finally:
        _cleanup(item_ids=[item_id])


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_rbac_customer_rep_forbidden_pm_and_admin_allowed():
    checker = require_role(ROLE_PROCUREMENT_MANAGER)  # same call vema_reorder_router._approver makes

    with pytest.raises(Exception) as exc_info:
        checker(user={"id": "x", "role": ROLE_CUSTOMER_REP, "name": "CR", "email": "cr@test"})
    assert getattr(exc_info.value, "status_code", None) == 403

    # Both do not raise.
    checker(user={"id": "x", "role": ROLE_PROCUREMENT_MANAGER, "name": "PM", "email": "pm@test"})
    checker(user={"id": "x", "role": ROLE_ADMIN, "name": "Admin", "email": "admin@test"})


# ---------------------------------------------------------------------------
# One bad item never aborts the scan
# ---------------------------------------------------------------------------

def test_one_bad_item_does_not_abort_the_scan():
    good_id = "ZTEST-SCAN-GOOD"
    bad_id = "ZTEST-SCAN-BAD"
    _insert_item(good_id, current_stock=5)
    _insert_item(bad_id, current_stock=5)
    try:
        real_fn = vema._create_request_for_item

        def _flaky(db, item):
            if item["item_id"] == bad_id:
                raise RuntimeError("simulated failure for the bad item only")
            return real_fn(db, item)

        with patch("vema_reorder_service._create_request_for_item", side_effect=_flaky):
            with db_session() as db:
                created = vema.scan_and_create_requests(db)

        created_ids = {c["item_id"] for c in created}
        assert good_id in created_ids
        assert bad_id not in created_ids  # failed, but didn't take the scan down with it
    finally:
        _cleanup(item_ids=[good_id, bad_id])
