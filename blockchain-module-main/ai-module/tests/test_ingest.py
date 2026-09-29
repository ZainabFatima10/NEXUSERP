"""
Feature C — dataset ingestion. Needs a live Postgres (writes real rows via
rag.vector_store, then cleans up by source). Skips cleanly if unreachable.
"""
import json
import pytest
import sqlalchemy as sa

from database import db_session
from rag.vector_store import store
from rag.ingest import ingest_file


def _db_available() -> bool:
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1 FROM rag_documents LIMIT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live Postgres with rag_documents (migration 007)")


@pytest.fixture
def cleanup_source():
    sources = []
    yield sources
    with db_session() as db:
        for s in sources:
            store.delete(db, source=s)


def test_jsonl_ingestion_happy_path(tmp_path, cleanup_source):
    f = tmp_path / "good.jsonl"
    f.write_text(
        '{"question": "How do I pay my bill?", "answer": "Use the app or online banking."}\n'
        '{"question": "What is a smart meter?", "answer": "A digital meter with remote reading."}\n',
        encoding="utf-8",
    )
    cleanup_source.append("good.jsonl")
    report = ingest_file(f)
    assert report.ingested == 2
    assert report.skipped == []
    assert report.duplicates == []


def test_bad_rows_are_skipped_not_fatal(tmp_path, cleanup_source):
    f = tmp_path / "bad.jsonl"
    f.write_text(
        '{"question": "valid one", "answer": "valid answer"}\n'
        '{"question": "", "answer": "missing question"}\n'
        "{not valid json\n"
        '{"question": "valid two", "answer": ""}\n',
        encoding="utf-8",
    )
    cleanup_source.append("bad.jsonl")
    report = ingest_file(f)
    assert report.ingested == 1  # only the one fully-valid row
    assert len(report.skipped) == 3  # empty question, malformed json, empty answer


def test_near_duplicate_questions_are_deduped(tmp_path, cleanup_source):
    f = tmp_path / "dupes.jsonl"
    f.write_text(
        '{"question": "How do I report a wrong bill?", "answer": "File a complaint."}\n'
        '{"question": "how do i report a wrong bill?", "answer": "Same thing, different wording."}\n'
        '{"question": "How do I request a new connection?", "answer": "Apply at your DISCO office."}\n',
        encoding="utf-8",
    )
    cleanup_source.append("dupes.jsonl")
    report = ingest_file(f)
    assert report.ingested == 2
    assert len(report.duplicates) == 1


def test_csv_ingestion_with_custom_column_mapping(tmp_path, cleanup_source):
    f = tmp_path / "export.csv"
    f.write_text("Q,A,Cat\nHow do I get a new meter?,Apply via the portal.,Meter Issues\n", encoding="utf-8")
    cleanup_source.append("export.csv")
    report = ingest_file(f, column_map={"question": "Q", "answer": "A", "category": "Cat"})
    assert report.ingested == 1


def test_reingesting_the_same_file_does_not_duplicate(tmp_path, cleanup_source):
    # The spec's own acceptance test: "run ingestion twice -> no duplicate
    # rows." ingest_file() checks existing DB rows for this source (not just
    # the in-batch set) before inserting, so a second run of the identical
    # file is a no-op rather than a second copy.
    f = tmp_path / "idempotent.jsonl"
    f.write_text('{"question": "How do I check my bill history?", "answer": "Via the portal."}\n', encoding="utf-8")
    cleanup_source.append("idempotent.jsonl")
    first = ingest_file(f)
    second = ingest_file(f)
    assert first.ingested == 1
    assert second.ingested == 0
    assert len(second.duplicates) == 1
    with db_session() as db:
        rows = db.execute(
            sa.text("SELECT COUNT(*) FROM rag_documents WHERE source = :s"), {"s": "idempotent.jsonl"}
        ).scalar()
    assert rows == 1
