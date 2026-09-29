"""
CLI: python -m rag.ingest_tickets
Full (re)index of resolved_ticket documents — see resolved_tickets.py for
what gets indexed and the PII-scrubbing this relies on. Also runs
automatically, incrementally and non-fatally, whenever a ticket is resolved
(vema_orchestrator._resolve) — this CLI is for a full rebuild, e.g. after
changing RAG_INDEX_RESOLVED_TICKETS or the PII scrubbing logic.
"""
from database import db_session
from rag.resolved_tickets import rebuild_resolved_ticket_index, RAG_INDEX_RESOLVED_TICKETS


def main():
    if not RAG_INDEX_RESOLVED_TICKETS:
        print("RAG_INDEX_RESOLVED_TICKETS is off in .env — nothing to do. Set it to 'true' to enable.")
        return
    with db_session() as db:
        n = rebuild_resolved_ticket_index(db)
    print(f"Indexed {n} resolved tickets.")


if __name__ == "__main__":
    main()
