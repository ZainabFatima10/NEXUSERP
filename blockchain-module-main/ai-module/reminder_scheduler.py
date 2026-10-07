"""
NEXUS ERP — VEMA CR Reminder Scheduler
Section 5c requires nagging a Customer Representative every 30 minutes
(medium) / 15 minutes (critical) until an escalated ticket is resolved.
Implemented as a background job, not a blocking loop, using APScheduler —
the lightest-weight option that's already idiomatic for a single-process
FastAPI deployment like this one (no Redis/broker needed, unlike Celery
beat). See VEMA_BACKEND_WIRING.md for why APScheduler was chosen over
Celery beat.
"""
import uuid
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from database import db_session
from notification_service import notify_role
from taxonomy import REMINDER_INTERVAL_MINUTES
import shipment_chain_service
import vendor_orders
import payments
import notification_engine

_scheduler = None


def check_and_fire_reminders():
    """Runs every minute; only acts on tickets whose next_reminder_due has passed."""
    with db_session() as db:
        due = db.execute(
            text("""
                SELECT * FROM complaints
                WHERE status = 'escalated' AND next_reminder_due IS NOT NULL
                  AND next_reminder_due <= NOW()
            """)
        ).mappings().all()

        for row in due:
            interval = REMINDER_INTERVAL_MINUTES.get(row["severity"], 30)
            # Server-side "NOW() + N minutes" -- see vema_orchestrator._escalate()
            # for why a Python-side datetime.utcnow() must not be bound here.
            db.execute(
                text("""
                    UPDATE complaints SET
                      next_reminder_due = NOW() + (:minutes * INTERVAL '1 minute'),
                      reminder_count = reminder_count + 1,
                      last_reminded_at = NOW(),
                      updated_at = NOW()
                    WHERE id = :id
                """),
                {"minutes": interval, "id": row["id"]},
            )
            db.execute(
                text("""
                    INSERT INTO complaint_events (id, complaint_id, event_type, actor, content, metadata, created_at)
                    VALUES (:id, :cid, 'reminder', 'vema', :content, '{}'::jsonb, NOW())
                """),
                {
                    "id": str(uuid.uuid4()), "cid": row["id"],
                    "content": f"Reminder #{row['reminder_count'] + 1}: ticket still unresolved "
                               f"({row['severity']} severity, due every {interval} min).",
                },
            )
            notify_role(
                db, "customer_rep", "User Complaints",
                f"Reminder — {row['ticket_code']} still open",
                f"{row['severity'].capitalize()} ticket {row['ticket_code']} has been open since "
                f"{row['escalated_at']}. Please action or resolve it.",
                metadata={"ticket_id": str(row["id"]), "ticket_code": row["ticket_code"], "severity": row["severity"]},
            )


def _run_vendor_order_jobs():
    """Phase 2: vendor order expiry/reminders + chain tx retry. Each job
    gets its own db_session so one failing job can't take the others down
    with it (match the per-job isolation check_and_fire_reminders doesn't
    need, since it's the only VEMA job, but this scheduler now runs several
    unrelated job families in sequence)."""
    for job in (
        vendor_orders.check_vendor_order_expiry,
        vendor_orders.check_vendor_order_reminders,
        vendor_orders.check_arrival_reminders,
        vendor_orders.check_approval_reminders,
        vendor_orders.check_delayed_shipments,
        vendor_orders.check_vendor_status_checkins,
        vendor_orders.check_chain_health,
        payments.process_due_payouts,
    ):
        try:
            with db_session() as db:
                job(db)
        except Exception as e:
            print(f"[WARN] reminder_scheduler: {job.__name__} failed: {e}")


def _run_chain_retry_job():
    try:
        with db_session() as db:
            n = shipment_chain_service.retry_pending_chain_txs(db)
            if n:
                print(f"[OK] retry_pending_chain_txs: retried {n} pending transaction(s).")
    except Exception as e:
        print(f"[WARN] reminder_scheduler: chain tx retry failed: {e}")


def _run_notification_outbox_job():
    """Phase 3: sends queued staff emails (notification_outbox), with
    backoff retry on failure — see notification_engine.py."""
    try:
        with db_session() as db:
            n = notification_engine.process_notification_outbox(db)
            if n:
                print(f"[OK] process_notification_outbox: sent {n} queued email(s).")
    except Exception as e:
        print(f"[WARN] reminder_scheduler: notification outbox processing failed: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(check_and_fire_reminders, "interval", minutes=1, id="vema_reminder_check", max_instances=1)
    _scheduler.add_job(_run_vendor_order_jobs, "interval", minutes=5, id="vendor_order_checks", max_instances=1)
    _scheduler.add_job(_run_chain_retry_job, "interval", minutes=2, id="chain_tx_retry", max_instances=1)
    _scheduler.add_job(_run_notification_outbox_job, "interval", minutes=1, id="notification_outbox", max_instances=1)
    _scheduler.start()
    print("[OK] VEMA reminder scheduler started (checks every 1 minute).")
    print("[OK] Vendor order expiry/reminder checks started (every 5 minutes).")
    print("[OK] Chain tx retry job started (every 2 minutes).")
    print("[OK] Notification outbox job started (every 1 minute).")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
