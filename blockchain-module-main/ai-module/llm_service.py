"""
NEXUS ERP — VEMA NLU / Conversation Service
LLM calls go through llm_client.py (Gemini primary — free tier, no card
required; Mistral secondary for anyone who already has that key). See
llm_client.py's docstring for why there are two providers and how the
priority works.

Dev-mode fallback (no provider configured): a deterministic keyword
classifier + canned responses, so the full ticket lifecycle (classify ->
route -> auto-resolve/escalate) is testable without any API key — mirrors
the MODEL_LOADED fallback pattern already used in inventory_v2.py.
"""
import json
from typing import Optional

from taxonomy import TAXONOMY, default_severity_for, all_categories, subtypes_for
from echo_guard import strip_echo
from llm_client import chat_text, chat_json, is_available

LLM_AVAILABLE = is_available()


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

    parsed = chat_json(_CLASSIFY_SYSTEM_PROMPT, text, temperature=0.1)
    if parsed is None:
        return _keyword_classify(text)

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

    parsed = chat_json(
        _AUTO_RESOLVE_SYSTEM_PROMPT,
        f"Category: {category}\nSubtype: {subtype}\nComplaint: {description}",
        temperature=0.2,
    )
    if parsed is None:
        return {"resolved": False, "message": "Needs a Customer Representative."}
    return {"resolved": bool(parsed.get("resolved")), "message": parsed.get("message", "")}


# ---------------------------------------------------------------------------
# Conversational reply (chat/voice turn-by-turn)
# ---------------------------------------------------------------------------

_CHAT_SYSTEM_PROMPT = """You are VEMA, a helpful voice/chat assistant for a
Pakistani electricity utility's customers. Keep replies short (1-3 sentences),
empathetic, and in English only. You are logging a complaint. Respond to
what the customer needs next — do not repeat, quote, or paraphrase their
own words back to them. Never open a reply with phrases like "you said",
"I heard", "so you're saying", or "if I understand" — state the next step or
answer directly. Let them know it's been recorded as a ticket."""

_ECHO_RETRY_NOTICE = (
    "\nIMPORTANT: a previous attempt at this reply incorrectly repeated the "
    "customer's own words back to them. Do not do that — respond with only "
    "new content, no restatement of what they said."
)


def _fallback_chat_reply(ticket_code: Optional[str]) -> str:
    suffix = f" Your ticket reference is {ticket_code}." if ticket_code else ""
    return f"Thanks — I've logged your complaint.{suffix} Our team will follow up as needed."


def generate_chat_reply(customer_message: str, ticket_code: Optional[str] = None) -> str:
    """
    Returns a reply that never opens by restating customer_message (Feature
    A) — enforced by the system prompt, with echo_guard.strip_echo() as a
    safety net that survives prompt drift. Never raises; always returns
    something speakable.
    """
    fallback = _fallback_chat_reply(ticket_code)
    if not LLM_AVAILABLE:
        return fallback  # fixed acknowledgement, never echoes by construction

    reply = chat_text(_CHAT_SYSTEM_PROMPT, customer_message, temperature=0.4)
    if reply is None:
        return fallback

    cleaned, fired = strip_echo(reply, customer_message)
    if fired:
        print("[WARN] echo-guard stripped an echoed prefix from VEMA's chat reply")
        if not cleaned:
            # The whole reply was an echo — one stricter regeneration attempt.
            retry = chat_text(_CHAT_SYSTEM_PROMPT + _ECHO_RETRY_NOTICE, customer_message, temperature=0.4)
            cleaned = ""
            if retry:
                cleaned, _ = strip_echo(retry, customer_message)
            if not cleaned:
                cleaned = fallback
    return cleaned
