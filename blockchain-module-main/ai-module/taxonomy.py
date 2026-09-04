"""
NEXUS ERP — VEMA Complaint Taxonomy
Category -> subtypes + default severity, per Section 5 of the VEMA spec.
The NLU (llm_service.classify_complaint) starts from these defaults but can
override severity based on the actual complaint content.
"""
from typing import Optional

SMALL = "small"
MEDIUM = "medium"
CRITICAL = "critical"

# category -> (list of subtypes, default severity)
TAXONOMY = {
    "Billing Issues": {
        "subtypes": [
            "overbilling/incorrect meter reading",
            "estimated bill disputes",
            "late fee/surcharge disputes",
            "bill not received",
        ],
        "default_severity": SMALL,
    },
    "Meter Issues": {
        "subtypes": [
            "faulty/defective meter",
            "meter tampering allegation",
            "meter reading not updated",
            "request for meter replacement",
        ],
        "default_severity": MEDIUM,
    },
    "Power Supply Issues": {
        "subtypes": [
            "no electricity/outage",
            "frequent load shedding beyond schedule",
            "voltage fluctuation (low/high)",
            "unscheduled/unannounced outage",
        ],
        "default_severity": CRITICAL,
    },
    "New Connection / Disconnection": {
        "subtypes": [
            "new connection request delay",
            "wrongful disconnection",
            "reconnection delay after payment",
            "connection load change request",
        ],
        "default_severity": MEDIUM,
    },
    "Infrastructure Complaints": {
        "subtypes": [
            "damaged transformer",
            "fallen/damaged power lines",
            "faulty poles or exposed wiring (safety hazard)",
        ],
        "default_severity": CRITICAL,
    },
    "Customer Service": {
        "subtypes": [
            "staff behavior complaint",
            "complaint not resolved/no response",
            "long wait times at office",
        ],
        "default_severity": SMALL,
    },
    "Fraud/Theft": {
        "subtypes": [
            "suspected electricity theft (reported by consumer)",
            "unauthorized connection nearby",
        ],
        "default_severity": CRITICAL,
    },
    "Payment & Refund": {
        "subtypes": [
            "payment not reflected in account",
            "refund request",
            "online payment failure",
        ],
        "default_severity": MEDIUM,
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
