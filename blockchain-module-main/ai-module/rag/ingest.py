"""
NEXUS ERP — RAG Q&A Dataset Ingestion (Feature C)

CLI:
  python -m rag.ingest --path data/qa/ --rebuild
  python -m rag.ingest --path data/qa/seed_qa.jsonl
  python -m rag.ingest --path export.csv --question-col Question --answer-col Answer

Supports CSV, JSON (array of objects, or {"data": [...]})," JSONL, and XLSX
(if `openpyxl` is installed — degrades to a clear per-file skip otherwise,
never crashes the whole ingestion run). Column names default to
question/answer/category/language/source but are overridable per-format via
the config dict passed to `ingest_file()`, or the matching --*-col CLI flags,
so a public Q&A dataset with different column names can be dropped in with
just a mapping, no code changes.

A bad row (missing question/answer, unreadable cell, etc.) is logged and
skipped; it never aborts the batch (guardrail 5). Near-duplicate questions
(SequenceMatcher ratio >= 0.92 against anything already queued in this run)
are skipped too and counted separately.
"""
import argparse
import csv
import json
import os
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from sqlalchemy import text as sql_text

from database import db_session
from rag.vector_store import store, RagDocument

DEFAULT_COLUMN_MAP = {
    "question": "question", "answer": "answer", "category": "category",
    "language": "language", "source": "source",
}
DUPLICATE_THRESHOLD = 0.92


@dataclass
class IngestReport:
    ingested: int = 0
    skipped: list = None
    duplicates: list = None

    def __post_init__(self):
        self.skipped = self.skipped or []
        self.duplicates = self.duplicates or []

    def merge(self, other: "IngestReport"):
        self.ingested += other.ingested
        self.skipped.extend(other.skipped)
        self.duplicates.extend(other.duplicates)


def _is_near_duplicate(question: str, seen: list) -> bool:
    norm = question.lower().strip()
    return any(SequenceMatcher(None, norm, s).ratio() >= DUPLICATE_THRESHOLD for s in seen)


def _read_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError as e:
                yield i, {"__error__": str(e)}


def _read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("data", data) if isinstance(data, dict) else data
    for i, row in enumerate(rows):
        yield i, row


def _read_csv(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            yield i, row


def _read_xlsx(path: Path):
    try:
        from openpyxl import load_workbook
    except ImportError:
        print(f"[SKIP] {path}: openpyxl not installed — `pip install openpyxl` to ingest .xlsx files")
        return
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if not header:
        return
    header = [str(h) if h is not None else "" for h in header]
    for i, values in enumerate(rows_iter):
        yield i, dict(zip(header, values))


_READERS = {".jsonl": _read_jsonl, ".json": _read_json, ".csv": _read_csv, ".xlsx": _read_xlsx}


def ingest_file(path: Path, column_map: Optional[dict] = None, source_name: Optional[str] = None) -> IngestReport:
    report = IngestReport()
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        report.skipped.append((None, f"unsupported file type: {path.suffix}"))
        return report

    cmap = {**DEFAULT_COLUMN_MAP, **(column_map or {})}
    source = source_name or path.name

    # Dedup against every existing 'qa' question in the DB, not just what's
    # in the current batch — otherwise re-running ingest_file on the exact
    # same file (without --rebuild) duplicates every row, failing the
    # "ingest twice -> no duplicate rows" property the spec asks for. Scoped
    # to doc_type (not `source`): a per-row "source" column in the dataset
    # itself (this repo's seed_qa.jsonl has one) can differ from the
    # filename, so filtering by source here would silently miss existing
    # rows and re-duplicate them — caught by actually re-running this against
    # the real seed dataset, not just the unit test's single-source fixture.
    with db_session() as db:
        seen_questions: list = [
            row[0].lower().strip() for row in
            db.execute(sql_text("SELECT question FROM rag_documents WHERE doc_type = 'qa'")).all()
        ]
    documents = []

    for row_num, row in reader(path):
        if not isinstance(row, dict):
            report.skipped.append((row_num, "row is not an object/record"))
            continue
        if "__error__" in row:
            report.skipped.append((row_num, f"malformed row: {row['__error__']}"))
            continue
        try:
            question = str(row.get(cmap["question"], "") or "").strip()
            answer = str(row.get(cmap["answer"], "") or "").strip()
            if not question or not answer:
                report.skipped.append((row_num, "missing question or answer"))
                continue
            if _is_near_duplicate(question, seen_questions):
                report.duplicates.append((row_num, question))
                continue
            seen_questions.append(question.lower().strip())
            category = row.get(cmap["category"]) or None
            language = row.get(cmap["language"]) or "en"
            row_source = row.get(cmap["source"]) or source
            documents.append(RagDocument(
                doc_type="qa", question=question, answer=answer,
                category=category, language=language, source=row_source,
            ))
        except Exception as e:
            # One bad row must never abort the batch.
            report.skipped.append((row_num, f"unexpected error: {e}"))
            continue

    if documents:
        with db_session() as db:
            report.ingested = store.upsert(db, documents)
    return report


def ingest_path(path: Path, column_map: Optional[dict] = None, rebuild: bool = False) -> IngestReport:
    if rebuild:
        with db_session() as db:
            deleted = store.delete(db, doc_type="qa")
        print(f"[REBUILD] cleared {deleted} existing 'qa' documents")

    total = IngestReport()
    files = [path] if path.is_file() else sorted(
        p for p in path.iterdir() if p.suffix.lower() in _READERS
    )
    if not files:
        print(f"[WARN] no ingestible files found under {path}")
        return total

    for f in files:
        try:
            report = ingest_file(f, column_map)
        except Exception as e:
            # A whole corrupt FILE must not abort ingesting the rest of the directory.
            print(f"[SKIP] {f.name}: failed to ingest ({e})")
            continue
        print(f"[OK] {f.name}: ingested={report.ingested} skipped={len(report.skipped)} duplicates={len(report.duplicates)}")
        for row_num, reason in report.skipped[:5]:
            print(f"       skipped row {row_num}: {reason}")
        total.merge(report)
    return total


def main():
    parser = argparse.ArgumentParser(description="Ingest Q&A datasets into the RAG vector store")
    parser.add_argument("--path", required=True, help="File or directory of CSV/JSON/JSONL/XLSX Q&A data")
    parser.add_argument("--rebuild", action="store_true", help="Delete all existing 'qa' documents first")
    parser.add_argument("--question-col", default=None)
    parser.add_argument("--answer-col", default=None)
    parser.add_argument("--category-col", default=None)
    parser.add_argument("--language-col", default=None)
    parser.add_argument("--source-col", default=None)
    args = parser.parse_args()

    column_map = {}
    if args.question_col: column_map["question"] = args.question_col
    if args.answer_col: column_map["answer"] = args.answer_col
    if args.category_col: column_map["category"] = args.category_col
    if args.language_col: column_map["language"] = args.language_col
    if args.source_col: column_map["source"] = args.source_col

    total = ingest_path(Path(args.path), column_map or None, rebuild=args.rebuild)
    print(f"\n=== TOTAL: ingested={total.ingested} skipped={len(total.skipped)} duplicates={len(total.duplicates)} ===")


if __name__ == "__main__":
    main()
