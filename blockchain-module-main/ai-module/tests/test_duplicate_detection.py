"""
Feature D — duplicate/known-issue awareness. Never blocks ticket creation;
just links a new ticket to an existing open one in the same category+area
via `related_ticket_id`. Needs a live Postgres (real create_ticket() calls).
"""
import pytest
import sqlalchemy as sa

from database import db_session
from vema_orchestrator import create_ticket


def _db_available() -> bool:
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live Postgres connection")


def _cleanup(ticket_ids):
    with db_session() as db:
        for tid in ticket_ids:
            db.execute(sa.text("DELETE FROM complaint_events WHERE complaint_id = :id"), {"id": tid})
            db.execute(sa.text("UPDATE complaints SET related_ticket_id = NULL WHERE related_ticket_id = :id"), {"id": tid})
            db.execute(sa.text("DELETE FROM complaints WHERE id = :id"), {"id": tid})
        db.commit()


def test_second_ticket_in_same_category_and_area_links_to_the_first():
    created = []
    try:
        with db_session() as db:
            first = create_ticket(
                db, description="fallen power line reported for duplicate-detection test",
                channel="manual", vema_triggered=False, area="TestArea-DupCheck-99",
                override_category="Infrastructure Complaints",
                override_subtype="fallen/damaged power lines", override_severity="critical",
                logged_by_actor="test:duplicate_detection",
            )
            created.append(first["ticket_id"])
            assert "related_ticket_reference" not in first or first.get("related_ticket_reference") is None

            second = create_ticket(
                db, description="also seeing a damaged transformer, duplicate-detection test",
                channel="manual", vema_triggered=False, area="TestArea-DupCheck-99",
                override_category="Infrastructure Complaints",
                override_subtype="damaged transformer", override_severity="critical",
                logged_by_actor="test:duplicate_detection",
            )
            created.append(second["ticket_id"])

        assert second.get("related_ticket_reference") == first["reference_id"]
        with db_session() as db:
            row = db.execute(
                sa.text("SELECT related_ticket_id FROM complaints WHERE id = :id"), {"id": second["ticket_id"]}
            ).mappings().first()
        assert str(row["related_ticket_id"]) == first["ticket_id"]
    finally:
        _cleanup(created)


def test_creation_is_never_blocked_even_when_a_duplicate_exists():
    """The ticket still gets created (and routed/escalated normally) even
    though it's linked to an existing one — never a hard stop."""
    created = []
    try:
        with db_session() as db:
            first = create_ticket(
                db, description="no electricity reported, block-test",
                channel="manual", vema_triggered=False, area="TestArea-NeverBlocked-42",
                override_category="Power Supply Issues", override_subtype="no electricity/outage",
                override_severity="critical", logged_by_actor="test:duplicate_detection",
            )
            created.append(first["ticket_id"])
            second = create_ticket(
                db, description="also no power, block-test",
                channel="manual", vema_triggered=False, area="TestArea-NeverBlocked-42",
                override_category="Power Supply Issues", override_subtype="no electricity/outage",
                override_severity="critical", logged_by_actor="test:duplicate_detection",
            )
            created.append(second["ticket_id"])
        assert second["status"] == "escalated"  # routed normally, not suppressed
        assert second["ticket_id"] != first["ticket_id"]  # a real, separate ticket
    finally:
        _cleanup(created)


def test_different_category_same_area_is_not_treated_as_duplicate():
    created = []
    try:
        with db_session() as db:
            first = create_ticket(
                db, description="billing dispute, cross-category test",
                channel="manual", vema_triggered=False, area="TestArea-CrossCat-7",
                override_category="Billing Issues", override_subtype="bill not received",
                override_severity="small", logged_by_actor="test:duplicate_detection",
            )
            created.append(first["ticket_id"])
            second = create_ticket(
                db, description="power outage, cross-category test",
                channel="manual", vema_triggered=False, area="TestArea-CrossCat-7",
                override_category="Power Supply Issues", override_subtype="no electricity/outage",
                override_severity="critical", logged_by_actor="test:duplicate_detection",
            )
            created.append(second["ticket_id"])
        assert second.get("related_ticket_reference") is None
    finally:
        _cleanup(created)
