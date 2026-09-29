"""
NEXUS ERP — RAG Vector Store (Features C + D)

A small interface (upsert / search / delete) in front of Postgres+pgvector
so the backend is swappable (the spec's own requirement) — e.g. to
FAISS/Chroma on an environment where pgvector genuinely isn't available.
pgvector was tested here (`CREATE EXTENSION vector` on the live nexus_db
container) and works, so it's the only implementation actually built.

All documents live in one table (`rag_documents`, migration 007),
distinguished by `doc_type`: 'qa' (Feature C), 'category_kb' /
'resolved_ticket' (Feature D).
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.orm import Session

from rag.embeddings import embed_texts, embed_query, to_pgvector_literal, EMBEDDING_DIM


@dataclass
class RagDocument:
    doc_type: str            # qa | category_kb | resolved_ticket
    question: str
    answer: str
    category: Optional[str] = None
    language: str = "en"
    source: Optional[str] = None
    related_ticket_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    id: Optional[str] = None


@dataclass
class RagSearchResult:
    id: str
    doc_type: str
    question: str
    answer: str
    category: Optional[str]
    source: Optional[str]
    related_ticket_id: Optional[str]
    score: float  # cosine similarity, 1.0 = identical, 0.0 = orthogonal
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """Interface — see PgVectorStore for the implementation actually used."""

    def upsert(self, db: Session, documents: List[RagDocument]) -> int:
        raise NotImplementedError

    def search(
        self, db: Session, query: str, top_k: int = 5,
        doc_type: Optional[str] = None, category: Optional[str] = None,
        min_score: float = 0.0,
    ) -> List[RagSearchResult]:
        raise NotImplementedError

    def delete(self, db: Session, doc_type: Optional[str] = None, source: Optional[str] = None) -> int:
        raise NotImplementedError

    def count(self, db: Session, doc_type: Optional[str] = None) -> int:
        raise NotImplementedError


class PgVectorStore(VectorStore):
    def upsert(self, db: Session, documents: List[RagDocument]) -> int:
        if not documents:
            return 0
        embeddings = embed_texts([d.question for d in documents])
        inserted = 0
        for doc, emb in zip(documents, embeddings):
            doc_id = doc.id or str(uuid.uuid4())
            db.execute(
                text("""
                    INSERT INTO rag_documents (
                        id, doc_type, question, answer, category, language, source,
                        related_ticket_id, embedding, metadata, updated_at
                    ) VALUES (
                        :id, :doc_type, :question, :answer, :category, :language, :source,
                        :related_ticket_id, CAST(:embedding AS vector), CAST(:metadata AS jsonb), NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        question = EXCLUDED.question, answer = EXCLUDED.answer,
                        category = EXCLUDED.category, language = EXCLUDED.language,
                        source = EXCLUDED.source, related_ticket_id = EXCLUDED.related_ticket_id,
                        embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                """),
                {
                    "id": doc_id, "doc_type": doc.doc_type, "question": doc.question,
                    "answer": doc.answer, "category": doc.category, "language": doc.language,
                    "source": doc.source, "related_ticket_id": doc.related_ticket_id,
                    "embedding": to_pgvector_literal(emb),
                    "metadata": __import__("json").dumps(doc.metadata or {}),
                },
            )
            inserted += 1
        db.commit()
        return inserted

    def search(
        self, db: Session, query: str, top_k: int = 5,
        doc_type: Optional[str] = None, category: Optional[str] = None,
        min_score: float = 0.0,
    ) -> List[RagSearchResult]:
        query_emb = to_pgvector_literal(embed_query(query))
        filters = "WHERE 1=1"
        params: dict = {"q": query_emb, "k": top_k}
        if doc_type:
            filters += " AND doc_type = :doc_type"
            params["doc_type"] = doc_type
        if category:
            filters += " AND category = :category"
            params["category"] = category

        rows = db.execute(
            text(f"""
                SELECT id, doc_type, question, answer, category, source, related_ticket_id, metadata,
                       1 - (embedding <=> CAST(:q AS vector)) AS score
                FROM rag_documents
                {filters}
                ORDER BY embedding <=> CAST(:q AS vector)
                LIMIT :k
            """),
            params,
        ).mappings().all()

        results = [
            RagSearchResult(
                id=str(r["id"]), doc_type=r["doc_type"], question=r["question"],
                answer=r["answer"], category=r["category"], source=r["source"],
                related_ticket_id=str(r["related_ticket_id"]) if r["related_ticket_id"] else None,
                score=float(r["score"]), metadata=r["metadata"] or {},
            )
            for r in rows
        ]
        return [r for r in results if r.score >= min_score]

    def delete(self, db: Session, doc_type: Optional[str] = None, source: Optional[str] = None) -> int:
        filters = "WHERE 1=1"
        params: dict = {}
        if doc_type:
            filters += " AND doc_type = :doc_type"
            params["doc_type"] = doc_type
        if source:
            filters += " AND source = :source"
            params["source"] = source
        result = db.execute(text(f"DELETE FROM rag_documents {filters}"), params)
        db.commit()
        return result.rowcount or 0

    def count(self, db: Session, doc_type: Optional[str] = None) -> int:
        if doc_type:
            return db.execute(
                text("SELECT COUNT(*) FROM rag_documents WHERE doc_type = :dt"), {"dt": doc_type}
            ).scalar()
        return db.execute(text("SELECT COUNT(*) FROM rag_documents")).scalar()


store = PgVectorStore()
