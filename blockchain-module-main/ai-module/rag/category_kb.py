"""
NEXUS ERP — RAG category_kb source (Feature D, source 1)
Built automatically FROM the canonical taxonomy (taxonomy.py) — never
maintained separately, so it can never drift from the categories the rest
of the system classifies against. One rag_documents row per category:
question = description + example phrases (what gets embedded/matched
against an incoming complaint), answer = the guidance text spoken while
filing.
"""
from sqlalchemy.orm import Session

from taxonomy import TAXONOMY
from rag.vector_store import store, RagDocument


def rebuild_category_kb(db: Session) -> int:
    """Idempotent — safe to call any time the taxonomy changes; always wipes
    and rebuilds every category_kb document from the current taxonomy."""
    store.delete(db, doc_type="category_kb")

    documents = []
    for category, info in TAXONOMY.items():
        examples = info["example_phrases"]["en"] + info["example_phrases"]["roman_ur"]
        question_text = f"{info['description']} Example complaints: {'; '.join(examples)}."
        answer_text = info.get("guidance") or info["routing_hint"]
        documents.append(RagDocument(
            doc_type="category_kb",
            question=question_text,
            answer=answer_text,
            category=category,
            source="taxonomy",
            metadata={
                "code": info["code"],
                "default_severity": info["default_severity"],
                "required_fields": info["required_fields"],
                "routing_hint": info["routing_hint"],
            },
        ))
    return store.upsert(db, documents)
