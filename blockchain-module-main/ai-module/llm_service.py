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
Pakistani electricity utility (DISCO). First decide whether the customer's
message is actually a complaint about THIS DISCO's electricity service —
billing, meters, power supply/outages, connections, infrastructure hazards,
customer service experience with this DISCO, fraud/tampering, or payment for
electricity. Set "in_scope" to true only for those. If it's about something
else entirely (a different utility or company, an unrelated personal/product
issue, a vague or nonsensical message, or anything not about this DISCO's
electricity service), set "in_scope" to false and leave category/subtype/
severity as null — do not force it into a category just because one exists.

If in_scope is true, classify it into exactly one category and subtype from
this taxonomy, and pick a severity (small, medium, or critical). Use the
given default severity unless the complaint's content clearly warrants a
different one (e.g. a "bill not received" complaint that also mentions the
customer has been disconnected should be escalated above its category
default).

Taxonomy (category -> subtypes -> default severity -> details normally needed
to act on it, "required_fields"):
{json.dumps(TAXONOMY, indent=2)}

If in_scope is true, also decide whether something important from the chosen
category's required_fields is genuinely missing from what the customer said,
AND the customer could reasonably be expected to know it right now (e.g. no
area/location for an outage, no meter number for a meter fault). If so,
include ONE short, natural, spoken-friendly follow-up question for the
single most important missing detail. If the complaint already covers
enough to act on, or in_scope is false, followup_question must be null —
never ask just because a field exists in the list.

Respond with ONLY a JSON object: {{"in_scope": true|false, "category": "..." or
null, "subtype": "..." or null, "severity": "small|medium|critical" or null,
"summary": "one sentence summary", "followup_question": "..." or null}}"""


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
            "in_scope": True,
            "category": best_category,
            "subtype": best_subtype,
            "severity": default_severity_for(best_category, best_subtype),
            "summary": text.strip()[:200],
        }

    for category in TAXONOMY:
        if category.split()[0].lower() in lower:
            subtype = TAXONOMY[category]["subtypes"][0]
            return {
                "in_scope": True,
                "category": category,
                "subtype": subtype,
                "severity": default_severity_for(category, subtype),
                "summary": text.strip()[:200],
            }
    # No keyword signal at all — likely not a genuine electricity-service
    # complaint. Still return a valid fallback category/subtype (not None):
    # create_ticket() never refuses to file regardless of in_scope (by
    # design — see classify_complaint's docstring), so if this somehow
    # reaches it directly, ticket creation keeps working exactly as it
    # always has. in_scope=False is purely an advisory signal that
    # /api/complaints/preview uses to decline politely before ever getting
    # this far. No reliable way to detect "unrelated" from keywords alone
    # (unlike the follow-up question), so dev-mode is conservative here —
    # worth tightening once the real classifier output can be compared.
    return {
        "in_scope": False,
        "category": "Customer Service",
        "subtype": "complaint not resolved/no response",
        "severity": "medium",
        "summary": text.strip()[:200],
    }


def classify_complaint(text: str) -> dict:
    """
    Returns {in_scope, category, subtype, severity, summary, followup_question}.
    in_scope and followup_question are both folded into this one call rather
    than extra LLM round-trips — Gemini's free tier caps at 20 requests/day
    per model (confirmed live, see VEMA_RAG.md), so a separate call for
    either would add real quota cost for zero benefit, since the model
    already has everything it needs in this one prompt. Both are
    suggest-only: category/subtype/severity are ALWAYS a valid taxonomy
    entry regardless of in_scope, so create_ticket() (which reads these
    keys directly, no None-handling) never breaks or refuses to file —
    in_scope is consumed only by /api/complaints/preview, which uses it to
    decline out-of-scope messages politely before a ticket is ever drafted.
    Any failure (no provider, rate limit, bad JSON) falls back to the
    keyword classifier, same as always.
    """
    if not LLM_AVAILABLE:
        result = _keyword_classify(text)
        result["followup_question"] = None  # deciding what's *missing* needs real language
        return result                        # understanding, not a keyword match — dev-mode skips it

    parsed = chat_json(_CLASSIFY_SYSTEM_PROMPT, text, temperature=0.1)
    if parsed is None:
        result = _keyword_classify(text)
        result["followup_question"] = None
        return result

    if parsed.get("in_scope") is False:
        return {
            "in_scope": False,
            "category": "Customer Service",
            "subtype": "complaint not resolved/no response",
            "severity": "medium",
            "summary": parsed.get("summary", text.strip()[:200]),
            "followup_question": None,
        }

    category = parsed.get("category")
    subtype = parsed.get("subtype")
    if category not in TAXONOMY or subtype not in subtypes_for(category):
        # Model returned something outside the taxonomy — fall back safely.
        result = _keyword_classify(text)
        result["followup_question"] = None
        return result

    followup = parsed.get("followup_question")
    return {
        "in_scope": True,
        "category": category,
        "subtype": subtype,
        "severity": parsed.get("severity") or default_severity_for(category, subtype),
        "summary": parsed.get("summary", text.strip()[:200]),
        "followup_question": followup.strip() if isinstance(followup, str) and followup.strip() else None,
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
answer directly. Let them know it's been recorded as a ticket, but NEVER
state, invent, or guess a specific ticket number/reference — you are not
given the real one, and the app displays it separately. Say only that it
has been logged, not what its number is."""

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
