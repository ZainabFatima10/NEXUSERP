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


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(check_and_fire_reminders, "interval", minutes=1, id="vema_reminder_check", max_instances=1)
    _scheduler.start()
    print("[OK] VEMA reminder scheduler started (checks every 1 minute).")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
