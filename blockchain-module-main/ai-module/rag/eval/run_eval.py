"""
NEXUS ERP — RAG Evaluation (Feature C point 8)
Usage: python -m rag.eval.run_eval

Reports:
  - Retrieval hit@k (k=1,3,5) for in-domain queries: does the correct answer
    (identified by a keyword expected to appear in it) show up in the top-k?
  - No-answer precision for out-of-domain queries: does retrieval correctly
    come back empty (honest "I don't know"), rather than a false hit?
  - A basic groundedness spot-check: every "grounded" reply must be built
    from retrieved context, never fabricated — checked structurally here
    (grounded=True always carries sources; grounded=False always carries
    none) rather than by semantic judgment, which this eval script can't do
    without a second LLM call.

Held-out set: rag/eval/eval_set.jsonl — paraphrases of the seed dataset's
topics, not copies of its exact questions, plus genuinely out-of-domain
queries. Run `python -m rag.ingest --path data/qa/ --rebuild` first so the
seed corpus is actually loaded.
"""
import json
from pathlib import Path

from database import db_session
from rag.retrieval import retrieve
from rag.generation import generate_answer

EVAL_SET_PATH = Path(__file__).parent / "eval_set.jsonl"
K_VALUES = (1, 3, 5)


def _load_eval_set():
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run():
    cases = _load_eval_set()
    in_domain = [c for c in cases if c.get("in_domain", True)]
    out_domain = [c for c in cases if not c.get("in_domain", True)]

    hits_at_k = {k: 0 for k in K_VALUES}
    groundedness_consistent = 0
    no_answer_correct = 0

    with db_session() as db:
        print(f"\n=== In-domain retrieval (n={len(in_domain)}) ===")
        for case in in_domain:
            results = retrieve(db, case["query"], doc_type="qa", top_k=max(K_VALUES))
            answers_lower = [r.answer.lower() for r in results]
            keyword = case["expect_keyword"].lower()
            for k in K_VALUES:
                if any(keyword in a for a in answers_lower[:k]):
                    hits_at_k[k] += 1
            found_at = next((i + 1 for i, a in enumerate(answers_lower) if keyword in a), None)
            status = f"hit @ {found_at}" if found_at else "MISS"
            print(f"  [{status:8}] {case['query']!r}")

            gen = generate_answer(case["query"], results)
            consistent = bool(gen["grounded"]) == bool(gen["sources"])
            groundedness_consistent += int(consistent)

        print(f"\n=== Out-of-domain no-answer precision (n={len(out_domain)}) ===")
        for case in out_domain:
            results = retrieve(db, case["query"], doc_type="qa", top_k=max(K_VALUES))
            gen = generate_answer(case["query"], results)
            correct = not gen["grounded"]
            no_answer_correct += int(correct)
            print(f"  [{'OK' if correct else 'FALSE POSITIVE':14}] {case['query']!r} -> grounded={gen['grounded']}")

    n_in = len(in_domain) or 1
    n_out = len(out_domain) or 1
    print("\n=== Summary ===")
    for k in K_VALUES:
        print(f"  hit@{k}: {hits_at_k[k]}/{len(in_domain)} ({100 * hits_at_k[k] / n_in:.0f}%)")
    print(f"  groundedness-consistency (in-domain): {groundedness_consistent}/{len(in_domain)} ({100 * groundedness_consistent / n_in:.0f}%)")
    print(f"  no-answer precision (out-of-domain):  {no_answer_correct}/{len(out_domain)} ({100 * no_answer_correct / n_out:.0f}%)")


if __name__ == "__main__":
    run()
