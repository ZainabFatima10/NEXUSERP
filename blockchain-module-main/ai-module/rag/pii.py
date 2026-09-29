"""
NEXUS ERP — PII Scrubbing (Feature D)
Used before any resolved-ticket text is embedded/indexed. Two layers of
defense, see rag/resolved_tickets.py for why this is structured the way it is:

  1. resolved_ticket documents are built from category+subtype (a fixed
     taxonomy vocabulary — no free text, no PII by construction) for the
     retrieval "question", never the raw customer-written description.
  2. The staff-written resolution note (free text, so it CAN contain a name,
     number, etc. even though it's written by staff, not the customer) still
     goes through the regex scrubbing in this module before being indexed.

Regex-based PII detection is inherently imperfect (no NER model available —
see rag/embeddings.py's docstring on why a local ML model isn't usable on
this machine). Phone/CNIC/email/long-digit-sequence patterns are covered
with reasonable confidence; free-form name detection is NOT reliable via
regex alone and is intentionally NOT attempted beyond removing a ticket's
own known customer_name string (exact match) when it's supplied — this is a
disclosed limitation, not a solved problem. Given layer 1 above, the blast
radius of a residual leak here is limited to whatever staff happened to
type in a resolution note.
"""
import re
from typing import Optional

_PHONE_RE = re.compile(r"(\+?92[\s-]?)?0?3\d{2}[\s-]?\d{7}\b")          # Pakistani mobile: 03XXXXXXXXX / +923XXXXXXXXX
_CNIC_RE = re.compile(r"\b\d{5}-?\d{7}-?\d\b")                          # CNIC: 13 digits, dashes optional
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_LONG_DIGITS_RE = re.compile(r"\b\d{6,}\b")                             # catch-all: account/meter/reference numbers


def scrub_text(text: Optional[str], customer_name: Optional[str] = None) -> str:
    """Returns text with phone numbers, CNICs, emails, long digit sequences
    (account/meter/reference numbers), and the ticket's own known customer
    name redacted. Never raises — returns "" for falsy input."""
    if not text:
        return ""
    scrubbed = text
    if customer_name and customer_name.strip():
        # Exact-match redaction of the specific name on this ticket — far
        # more reliable than generic name-detection regex, and the only
        # name-scrubbing this module attempts (see module docstring).
        scrubbed = re.sub(re.escape(customer_name.strip()), "[name removed]", scrubbed, flags=re.IGNORECASE)
    scrubbed = _EMAIL_RE.sub("[email removed]", scrubbed)
    scrubbed = _CNIC_RE.sub("[cnic removed]", scrubbed)
    scrubbed = _PHONE_RE.sub("[phone removed]", scrubbed)
    scrubbed = _LONG_DIGITS_RE.sub("[number removed]", scrubbed)
    return scrubbed.strip()


def contains_pii(text: str) -> bool:
    """Best-effort check used by tests — True if any of the regex patterns
    still match. Does not (cannot) detect free-form names."""
    if not text:
        return False
    return bool(_EMAIL_RE.search(text) or _CNIC_RE.search(text) or _PHONE_RE.search(text) or _LONG_DIGITS_RE.search(text))
