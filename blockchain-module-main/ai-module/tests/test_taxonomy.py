"""
Feature B — the single-source-of-truth taxonomy: category<->code round-trip,
reference metadata shape, and severity resolution (defaults + overrides).
Pure/no DB — see test_reference_id.py for the DB-backed ticket-reference tests.
"""
from taxonomy import (
    TAXONOMY, all_categories, subtypes_for, is_valid_category_subtype,
    default_severity_for, code_for, category_for_code, required_fields_for,
    guidance_for, reference_table, SMALL, MEDIUM, CRITICAL,
)

EXPECTED_CATEGORIES = {
    "Billing Issues", "Meter Issues", "Power Supply Issues",
    "New Connection / Disconnection", "Infrastructure Complaints",
    "Customer Service", "Fraud/Theft", "Payment & Refund",
}


def test_exactly_the_eight_existing_categories():
    # Feature B requires using the categories already in the codebase, not
    # inventing new ones.
    assert set(all_categories()) == EXPECTED_CATEGORIES
    assert len(all_categories()) == 8


def test_every_category_has_a_unique_code():
    codes = [info["code"] for info in TAXONOMY.values()]
    assert len(codes) == len(set(codes)), "category codes must be unique"
    assert all(code.isupper() and code.isalpha() for code in codes)


def test_code_for_and_category_for_code_round_trip():
    for category in all_categories():
        code = code_for(category)
        assert category_for_code(code) == category


def test_code_for_unknown_category_falls_back_to_misc():
    assert code_for("Not A Real Category") == "MISC"
    assert category_for_code("MISC") is None


def test_every_category_has_full_reference_metadata():
    for category, info in TAXONOMY.items():
        assert info["description"], f"{category} missing description"
        assert info["routing_hint"], f"{category} missing routing_hint"
        assert info["default_severity"] in (SMALL, MEDIUM, CRITICAL)
        assert info["subtypes"], f"{category} has no subtypes"
        assert info["example_phrases"]["en"], f"{category} missing English examples"
        assert info["example_phrases"]["roman_ur"], f"{category} missing Roman-Urdu examples"
        assert required_fields_for(category), f"{category} missing required_fields"


def test_guidance_is_short_and_speakable():
    # Feature D requires guidance to be 1-2 short sentences, no markdown/URLs.
    for category in all_categories():
        text = guidance_for(category)
        assert text, f"{category} missing guidance"
        assert len(text) < 200
        assert "http" not in text.lower()
        assert "#" not in text and "*" not in text


def test_default_severity_matches_category():
    assert default_severity_for("Billing Issues", None) == SMALL
    assert default_severity_for("Power Supply Issues", None) == CRITICAL
    assert default_severity_for("Meter Issues", None) == MEDIUM


def test_subtype_override_beats_category_default():
    # "wrongful disconnection" overrides its category's medium default.
    assert default_severity_for("New Connection / Disconnection", "wrongful disconnection") == CRITICAL


def test_unknown_category_defaults_to_medium():
    assert default_severity_for("Not A Real Category", None) == MEDIUM


def test_is_valid_category_subtype():
    assert is_valid_category_subtype("Billing Issues", "bill not received") is True
    assert is_valid_category_subtype("Billing Issues", "no electricity/outage") is False
    assert is_valid_category_subtype("Not A Real Category", "anything") is False


def test_reference_table_shape_matches_categories_endpoint_contract():
    table = reference_table()
    assert len(table) == 8
    for record in table:
        assert set(record.keys()) == {
            "category", "code", "description", "default_severity",
            "routing_hint", "example_phrases", "subtypes",
            "required_fields", "guidance",
        }
        assert record["category"] in EXPECTED_CATEGORIES
