"""
NEXUS ERP — VEMA Complaint Taxonomy (single source of truth — Feature B)
Category -> subtypes + default severity + reference metadata, per Section 5
of the VEMA spec. The NLU (llm_service.classify_complaint) starts from these
defaults but can override severity based on the actual complaint content.

Everything downstream derives from this one module: the classification
prompt, the `/api/complaints/taxonomy` and `/api/complaints/categories`
endpoints (frontend fetches rather than duplicating this list), reference-ID
generation, and the RAG category_kb source (Feature D).

`required_fields` and `guidance` are SAMPLE CONTENT proposed for team
review, not official DISCO policy — see VEMA_RAG.md's "Decisions for
review" section. They exist so the complaint-intake follow-up logic and the
guidance spoken while filing have something concrete to work from; swap
them for reviewed copy before treating this as production content.
"""
from typing import Optional

SMALL = "small"
MEDIUM = "medium"
CRITICAL = "critical"

# category -> full reference record
TAXONOMY = {
    "Billing Issues": {
        "code": "BILL",
        "default_severity": SMALL,
        "description": "Disputes or questions about a bill's amount, timing, or delivery.",
        "routing_hint": "Billing / back-office team. Common disputes are auto-resolvable.",
        "example_phrases": {
            "en": ["my bill is too high this month", "I never received my bill", "the late fee on my bill is wrong"],
            "roman_ur": ["mera bill bohat zyada aya hai", "mujhe is mahine bill nahi mila", "late fee ghalat lagi hai"],
        },
        "subtypes": [
            "overbilling/incorrect meter reading",
            "estimated bill disputes",
            "late fee/surcharge disputes",
            "bill not received",
        ],
        # --- sample content, proposed for team review ---
        "required_fields": ["account_or_reference_number", "billing_month", "disputed_amount"],
        "guidance": "Please keep your latest bill and any past payment receipts on hand for verification.",
    },
    "Meter Issues": {
        "code": "METER",
        "default_severity": MEDIUM,
        "description": "Problems with the physical meter itself — faults, tampering, or replacement.",
        "routing_hint": "Field technical team for inspection/replacement.",
        "example_phrases": {
            "en": ["my meter is not working", "someone tampered with my meter", "my meter reading hasn't updated in months"],
            "roman_ur": ["mera meter kharab hai", "meter ke sath chher chhar hui hai", "meter reading update nahi ho rahi"],
        },
        "subtypes": [
            "faulty/defective meter",
            "meter tampering allegation",
            "meter reading not updated",
            "request for meter replacement",
        ],
        "required_fields": ["meter_number", "issue_type"],
        "guidance": "Please avoid opening or tampering with the meter yourself — a technician will inspect it.",
    },
    "Power Supply Issues": {
        "code": "POWER",
        "default_severity": CRITICAL,
        "description": "Outages, load-shedding beyond schedule, and voltage problems.",
        "routing_hint": "Grid operations — immediate escalation for outages.",
        "example_phrases": {
            "en": ["there is no electricity in my area", "load-shedding is longer than the schedule", "the voltage keeps fluctuating"],
            "roman_ur": ["hamare ilaqe mein bijli nahi hai", "load-shedding schedule se ziyada ho rahi hai", "voltage upar neeche ho raha hai"],
        },
        "subtypes": [
            "no electricity/outage",
            "frequent load shedding beyond schedule",
            "voltage fluctuation (low/high)",
            "unscheduled/unannounced outage",
        ],
        "required_fields": ["area_or_feeder", "duration", "time_started"],
        "guidance": "Please switch off sensitive appliances until supply is confirmed stable, to avoid voltage-related damage.",
    },
    "New Connection / Disconnection": {
        "code": "CONN",
        "default_severity": MEDIUM,
        "description": "New service requests, disconnections, reconnections, and load changes.",
        "routing_hint": "Connections desk.",
        "example_phrases": {
            "en": ["my new connection is delayed", "I was disconnected without notice", "I paid but I'm still not reconnected"],
            "roman_ur": ["naya connection late ho raha hai", "bina notice ke connection kaat diya", "payment ke baad bhi reconnect nahi hua"],
        },
        "subtypes": [
            "new connection request delay",
            "wrongful disconnection",
            "reconnection delay after payment",
            "connection load change request",
        ],
        "required_fields": ["application_or_account_number", "request_type"],
        "guidance": "Keep your application/payment receipt number ready — it speeds up verification.",
    },
    "Infrastructure Complaints": {
        "code": "INFRA",
        "default_severity": CRITICAL,
        "description": "Physical grid hazards — damaged equipment, fallen lines, exposed wiring.",
        "routing_hint": "Field safety team — treat as a safety hazard until confirmed otherwise.",
        "example_phrases": {
            "en": ["there's a fallen power line near my house", "the transformer is sparking", "exposed wires on the street"],
            "roman_ur": ["ghar ke paas bijli ki tar giri hui hai", "transformer se sparks nikal rahe hain", "sarak par khule taar hain"],
        },
        "subtypes": [
            "damaged transformer",
            "fallen/damaged power lines",
            "faulty poles or exposed wiring (safety hazard)",
        ],
        "required_fields": ["location", "urgency"],
        "guidance": "Please keep a safe distance and do not touch any wires or equipment — treat it as live.",
    },
    "Customer Service": {
        "code": "CSERV",
        "default_severity": SMALL,
        "description": "Feedback on staff conduct, unresolved complaints, or office wait times.",
        "routing_hint": "Customer relations / quality team.",
        "example_phrases": {
            "en": ["the staff at the office were rude", "my earlier complaint was never resolved", "I waited hours at the office"],
            "roman_ur": ["office ka staff bad tameezi se pesh aaya", "meri pichli complaint hal nahi hui", "office mein ghanton intezar kiya"],
        },
        "subtypes": [
            "staff behavior complaint",
            "complaint not resolved/no response",
            "long wait times at office",
        ],
        "required_fields": ["prior_ticket_reference_if_any"],
        "guidance": "If this relates to an earlier complaint, its ticket reference helps us follow up faster.",
    },
    "Fraud/Theft": {
        "code": "FRAUD",
        "default_severity": CRITICAL,
        "description": "Suspected electricity theft or unauthorized connections.",
        "routing_hint": "Anti-theft/vigilance team.",
        "example_phrases": {
            "en": ["my neighbor has an illegal connection", "I suspect electricity theft nearby"],
            "roman_ur": ["mere paros mein illegal connection hai", "mujhe bijli chori ka shak hai"],
        },
        "subtypes": [
            "suspected electricity theft (reported by consumer)",
            "unauthorized connection nearby",
        ],
        "required_fields": ["location", "description_of_activity"],
        "guidance": "You don't need to confront anyone — reporting the location and details is enough for us to act on.",
    },
    "Payment & Refund": {
        "code": "PAYMT",
        "default_severity": MEDIUM,
        "description": "Payments that haven't reflected, refund requests, and online payment failures.",
        "routing_hint": "Payments/finance team.",
        "example_phrases": {
            "en": ["my payment isn't showing on my account", "I want a refund", "online payment failed but money was deducted"],
            "roman_ur": ["meri payment account mein nahi dikh rahi", "mujhe refund chahiye", "online payment fail hui lekin paise kat gaye"],
        },
        "subtypes": [
            "payment not reflected in account",
            "refund request",
            "online payment failure",
        ],
        "required_fields": ["transaction_reference", "payment_date", "amount"],
        "guidance": "Please keep your transaction receipt or bank statement entry for this payment.",
    },
}

# Per-subtype override of the category default, for the specific examples
# called out in the spec (e.g. "wrongful disconnection" is critical even
# though its category default is medium).
SUBTYPE_SEVERITY_OVERRIDES = {
    "wrongful disconnection": CRITICAL,
    "no electricity/outage": CRITICAL,
    "unscheduled/unannounced outage": CRITICAL,
    "faulty poles or exposed wiring (safety hazard)": CRITICAL,
    "bill not received": SMALL,
}

REMINDER_INTERVAL_MINUTES = {
    MEDIUM: 30,
    CRITICAL: 15,
}


def default_severity_for(category: str, subtype: Optional[str]) -> str:
    if subtype and subtype in SUBTYPE_SEVERITY_OVERRIDES:
        return SUBTYPE_SEVERITY_OVERRIDES[subtype]
    cat = TAXONOMY.get(category)
    return cat["default_severity"] if cat else MEDIUM


def all_categories() -> list:
    return list(TAXONOMY.keys())


def subtypes_for(category: str) -> list:
    cat = TAXONOMY.get(category)
    return cat["subtypes"] if cat else []


def is_valid_category_subtype(category: str, subtype: str) -> bool:
    return subtype in subtypes_for(category)


# ---------------------------------------------------------------------------
# Feature B — reference metadata accessors
# ---------------------------------------------------------------------------

def code_for(category: str) -> str:
    """Short slug used in reference IDs (VEMA-<CODE>-...). 'MISC' for anything
    outside the taxonomy (should not normally happen — classification is
    validated against this module)."""
    cat = TAXONOMY.get(category)
    return cat["code"] if cat else "MISC"


_CODE_TO_CATEGORY = {v["code"]: k for k, v in TAXONOMY.items()}


def category_for_code(code: str) -> Optional[str]:
    return _CODE_TO_CATEGORY.get(code.upper())


def required_fields_for(category: str) -> list:
    cat = TAXONOMY.get(category)
    return list(cat["required_fields"]) if cat else []


def guidance_for(category: str) -> Optional[str]:
    cat = TAXONOMY.get(category)
    return cat.get("guidance") if cat else None


def reference_table() -> list:
    """The full reference list for GET /api/complaints/categories — one
    record per category, ticket counts added by the caller (needs a DB
    session, which this module deliberately doesn't depend on)."""
    return [
        {
            "category": name,
            "code": info["code"],
            "description": info["description"],
            "default_severity": info["default_severity"],
            "routing_hint": info["routing_hint"],
            "example_phrases": info["example_phrases"],
            "subtypes": info["subtypes"],
            "required_fields": info["required_fields"],
            "guidance": info.get("guidance"),
        }
        for name, info in TAXONOMY.items()
    ]
