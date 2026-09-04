"""
NEXUS ERP — VEMA NLU / Conversation Service (Mistral API)
The doc's "Rasa vs LLM API" decision is already resolved for this project:
LLM API via Mistral. No Rasa integration here.

Dev-mode fallback (MISTRAL_API_KEY unset): a deterministic keyword
classifier + canned responses, so the full ticket lifecycle (classify ->
route -> auto-resolve/escalate) is testable without a live API key —
mirrors the MODEL_LOADED fallback pattern already used in inventory_v2.py.
"""
import os, json
from typing import Optional
import httpx
from dotenv import load_dotenv

from taxonomy import TAXONOMY, default_severity_for, all_categories, subtypes_for

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

LLM_AVAILABLE = bool(MISTRAL_API_KEY)
if not LLM_AVAILABLE:
    print("[WARN] MISTRAL_API_KEY not set — VEMA NLU running in dev-mode "
          "keyword classifier instead of the Mistral API.")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = f"""You are VEMA, the complaint-intake classifier for a
Pakistani electricity utility (DISCO). Classify the customer's complaint into
exactly one category and subtype from this taxonomy, and pick a severity
(small, medium, or critical). Use the given default severity unless the
complaint's content clearly warrants a different one (e.g. a "bill not
received" complaint that also mentions the customer has been disconnected
should be escalated above its category default).

Taxonomy (category -> subtypes -> default severity):
{json.dumps(TAXONOMY, indent=2)}

Respond with ONLY a JSON object: {{"category": "...", "subtype": "...",
"severity": "small|medium|critical", "summary": "one sentence summary"}}"""


# Words too generic to distinguish between subtypes on their own (they show
# up across many taxonomy entries) — still counted, but not enough alone.
_STOPWORDS = {"request", "account", "reading", "issue", "issues", "office", "connection"}


def _keyword_classify(text: str) -> dict:
    """
    Deterministic fallback classifier — scores every subtype by how many of
    its distinctive keywords appear in the complaint text, and returns the
    highest-scoring match (not the first one found — several subtypes share
    generic words like "meter", so first-match-wins picks the wrong category
    for e.g. "faulty meter" matching a Billing subtype before Meter Issues).
    """
    lower = text.lower()
    best_category, best_subtype, best_score = None, None, 0

    for category, info in TAXONOMY.items():
        for subtype in info["subtypes"]:
            words = subtype.replace("/", " ").replace("(", " ").replace(")", " ").split()
            keywords = [w for w in words if len(w) > 3]
            score = sum(1 for k in keywords if k in lower)
            # A hit on a non-stopword keyword counts double — rewards
            # distinctive words (e.g. "faulty", "tampering") over ones that
            # recur across subtypes (e.g. "reading", "request").
            score += sum(1 for k in keywords if k in lower and k not in _STOPWORDS)
            if score > best_score:
                best_category, best_subtype, best_score = category, subtype, score

    if best_category:
        return {
            "category": best_category,
            "subtype": best_subtype,
            "severity": default_severity_for(best_category, best_subtype),
            "summary": text.strip()[:200],
        }

    for category in TAXONOMY:
        if category.split()[0].lower() in lower:
            subtype = TAXONOMY[category]["subtypes"][0]
            return {
                "category": category,
                "subtype": subtype,
                "severity": default_severity_for(category, subtype),
                "summary": text.strip()[:200],
            }
    return {
        "category": "Customer Service",
        "subtype": "complaint not resolved/no response",
        "severity": "medium",
        "summary": text.strip()[:200],
    }


def classify_complaint(text: str) -> dict:
    """Returns {category, subtype, severity, summary}."""
    if not LLM_AVAILABLE:
        return _keyword_classify(text)

    try:
        resp = httpx.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        category = parsed.get("category")
        subtype = parsed.get("subtype")
        if category not in TAXONOMY or subtype not in subtypes_for(category):
            # Model returned something outside the taxonomy — fall back safely.
            return _keyword_classify(text)
        return {
            "category": category,
            "subtype": subtype,
            "severity": parsed.get("severity") or default_severity_for(category, subtype),
            "summary": parsed.get("summary", text.strip()[:200]),
        }
    except Exception as e:
        print(f"[WARN] Mistral classification failed ({e}), falling back to keyword classifier")
        return _keyword_classify(text)


# ---------------------------------------------------------------------------
# Auto-resolution attempt (small / medium tickets)
# ---------------------------------------------------------------------------

_AUTO_RESOLVE_SYSTEM_PROMPT = """You are VEMA, a first-line automated resolution
assistant for a Pakistani electricity utility. Given a classified complaint,
either (a) resolve it automatically with a clear, specific resolution message
the customer will receive by email, or (b) decide it needs a human Customer
Representative. Respond with ONLY JSON: {"resolved": true|false, "message": "..."}.
Only resolve automatically for things genuinely safe to auto-resolve from
policy/FAQ-style knowledge (e.g. explaining a bill/late-fee policy, confirming
a duplicate bill was already reprocessed, general informational requests).
Never resolve safety hazards, outages, fraud, or anything requiring a site visit."""

# Category/subtype pairs the system is confident it can resolve without a human,
# used by the keyword fallback (and as a sanity backstop even with the LLM on).
_AUTO_RESOLVABLE_SUBTYPES = {
    "bill not received",
    "late fee/surcharge disputes",
    "long wait times at office",
}


def attempt_auto_resolution(category: str, subtype: str, description: str) -> dict:
    """Returns {resolved: bool, message: str}."""
    if not LLM_AVAILABLE:
        if subtype in _AUTO_RESOLVABLE_SUBTYPES:
            return {
                "resolved": True,
                "message": (
                    f"Thanks for reaching out. We've reviewed your '{subtype}' request "
                    f"under {category} and resolved it automatically — a corrected "
                    f"notice/statement has been queued to your registered contact details."
                ),
            }
        return {"resolved": False, "message": "Needs a Customer Representative."}

    try:
        resp = httpx.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": _AUTO_RESOLVE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Category: {category}\nSubtype: {subtype}\nComplaint: {description}"},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {"resolved": bool(parsed.get("resolved")), "message": parsed.get("message", "")}
    except Exception as e:
        print(f"[WARN] Mistral auto-resolution failed ({e}), escalating to CR")
        return {"resolved": False, "message": "Needs a Customer Representative."}


# ---------------------------------------------------------------------------
# Conversational reply (chat/voice turn-by-turn)
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_PROMPT = """You are VEMA, a helpful voice/chat assistant for a
Pakistani electricity utility's customers. Keep replies short (1-3 sentences),
empathetic, and in English only. You are logging a complaint — acknowledge
what the customer said and let them know it's been recorded as a ticket."""


def generate_chat_reply(customer_message: str, ticket_code: Optional[str] = None) -> str:
    if not LLM_AVAILABLE:
        suffix = f" Your ticket reference is {ticket_code}." if ticket_code else ""
        return f"Thanks — I've logged your complaint.{suffix} Our team will follow up as needed."
    try:
        resp = httpx.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": _CHAT_SYSTEM_PROMPT},
                    {"role": "user", "content": customer_message},
                ],
                "temperature": 0.4,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[WARN] Mistral chat reply failed ({e})")
        suffix = f" Your ticket reference is {ticket_code}." if ticket_code else ""
        return f"Thanks — I've logged your complaint.{suffix} Our team will follow up as needed."
