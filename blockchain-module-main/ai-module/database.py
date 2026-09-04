"""
NEXUS ERP — Database module
PostgreSQL via SQLAlchemy (async-ready sync wrapper for FastAPI)
"""
import os
from contextlib import contextmanager
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

load_dotenv()

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "nexus_erp")
DB_USER     = os.getenv("DB_USER", "nexus_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "nexus_pass")

DATABASE_URL = (
    f"postgresql+pg8000://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,         # reconnect on stale connections
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    """Context manager for use outside FastAPI DI (scripts, engines)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _apply_sql_file(conn, sql_path) -> None:
    with open(sql_path) as f:
        sql = f.read()
    # Execute statement-by-statement to avoid multi-statement issues
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                # Skip "already exists" / already-applied errors on re-run
                if "already exists" not in str(e).lower():
                    raise


def run_schema(sql_path: str = None):
    """
    Run the base schema, then every numbered migration file (NNN_*.sql,
    NNN > 001) in ascending order. Every migration is written to be
    idempotent (IF NOT EXISTS / ON CONFLICT / DROP-then-ADD constraint),
    so re-running this on every startup is safe.
    """
    import pathlib
    here = pathlib.Path(__file__).parent
    base = pathlib.Path(sql_path) if sql_path else (here / "001_schema.sql")

    migrations = sorted(
        p for p in here.glob("[0-9][0-9][0-9]_*.sql") if p.name != base.name
    )

    with engine.connect() as conn:
        _apply_sql_file(conn, base)
        conn.commit()
        for migration in migrations:
            _apply_sql_file(conn, migration)
            conn.commit()
            print(f"[OK] Migration applied: {migration.name}")
    print("[OK] Schema applied successfully.")


def check_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


if __name__ == "__main__":
    run_schema()
