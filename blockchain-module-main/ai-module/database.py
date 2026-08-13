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
    f"postgresql://{DB_USER}:{DB_PASSWORD}"
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


def run_schema(sql_path: str = None):
    """Run the SQL schema file to initialise / migrate tables."""
    import pathlib
    if sql_path is None:
        here = pathlib.Path(__file__).parent
        sql_path = here / "001_schema.sql"
    with open(sql_path) as f:
        sql = f.read()
    with engine.connect() as conn:
        # Execute statement-by-statement to avoid multi-statement issues
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    # Skip "already exists" errors on re-run
                    if "already exists" not in str(e).lower():
                        raise
        conn.commit()
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
