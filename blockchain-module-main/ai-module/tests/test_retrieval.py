"""
Feature C — retrieval (vector search + the lexical-overlap gate added after
a live test showed cosine similarity alone doesn't reliably separate
in-domain from out-of-domain text against this environment's hashing-based
embedding fallback — see retrieval.py's module docstring for the full story).
Needs a live Postgres with pgvector (migration 007) — skips cleanly if
unreachable, same pattern as test_reference_id.py.
"""
import pytest
import sqlalchemy as sa

from database import db_session
from rag.vector_store import store, RagDocument
from rag.retrieval import retrieve

TEST_SOURCE = "pytest_retrieval_suite"


def _db_available() -> bool:
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1 FROM rag_documents LIMIT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live Postgres with rag_documents (migration 007)")


@pytest.fixture
def seeded_docs():
    docs = [
        RagDocument(doc_type="qa", question="How do I report a wrong or overcharged bill?",
                    answer="File a billing complaint with your account number and disputed amount.",
                    category="Billing Issues", source=TEST_SOURCE),
        RagDocument(doc_type="qa", question="How can I pay my electricity bill online?",
                    answer="Use the NEXUS app, online banking, or an authorized franchise.",
                    category="Payment & Refund", source=TEST_SOURCE),
        RagDocument(doc_type="qa", question="What should I do if there is a power outage?",
                    answer="Check the load-shedding schedule first, then report it if unscheduled.",
                    category="Power Supply Issues", source=TEST_SOURCE),
    ]
    with db_session() as db:
        store.upsert(db, docs)
    yield docs
    with db_session() as db:
        store.delete(db, source=TEST_SOURCE)


def test_in_domain_query_returns_the_relevant_match_on_top(seeded_docs):
    with db_session() as db:
        results = retrieve(db, "my bill amount is wrong, how do I dispute it", doc_type="qa")
    assert results, "expected at least one match"
    assert "bill" in results[0].question.lower()


def test_out_of_domain_query_returns_nothing(seeded_docs):
    # This is the exact failure mode a live test caught: without the
    # lexical-overlap gate, this scored HIGHER against an unrelated doc than
    # some genuine paraphrases score against their own match.
    with db_session() as db:
        results = retrieve(db, "what is the capital of France", doc_type="qa")
    assert results == []


def test_category_filter_is_applied(seeded_docs):
    with db_session() as db:
        results = retrieve(db, "bill payment", doc_type="qa", category="Power Supply Issues")
    for r in results:
        assert r.category == "Power Supply Issues"


def test_delete_by_source_removes_only_that_sources_documents(seeded_docs):
    with db_session() as db:
        count_before = store.count(db, doc_type="qa")
        deleted = store.delete(db, source=TEST_SOURCE)
        count_after = store.count(db, doc_type="qa")
    assert deleted == 3
    assert count_after == count_before - 3
    # re-seed so the fixture's own teardown delete doesn't error on nothing —
    # harmless no-op delete either way, but keep the fixture symmetric
    with db_session() as db:
        store.upsert(db, seeded_docs)
