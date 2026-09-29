"""
Feature D — PII scrubbing, applied to resolved-ticket resolution notes
before they're indexed for RAG. See rag/pii.py's module docstring for the
two-layer defense this is part of (the "question" side never touches free
text at all — only category+subtype).
"""
from rag.pii import scrub_text, contains_pii


def test_phone_number_is_scrubbed():
    text = "Please call me back at 03001234567 to confirm."
    scrubbed = scrub_text(text)
    assert "03001234567" not in scrubbed
    assert not contains_pii(scrubbed)


def test_phone_number_with_country_code_is_scrubbed():
    text = "My number is +923211234567, call anytime."
    scrubbed = scrub_text(text)
    assert "3211234567" not in scrubbed


def test_cnic_is_scrubbed():
    text = "CNIC 35202-1234567-1 was used to verify the account."
    scrubbed = scrub_text(text)
    assert "35202-1234567-1" not in scrubbed
    assert not contains_pii(scrubbed)


def test_cnic_without_dashes_is_scrubbed():
    text = "cnic number 3520212345671 on file"
    scrubbed = scrub_text(text)
    assert "3520212345671" not in scrubbed


def test_email_is_scrubbed():
    text = "Customer confirmed via ahmed.khan@example.com that the issue is resolved."
    scrubbed = scrub_text(text)
    assert "ahmed.khan@example.com" not in scrubbed
    assert not contains_pii(scrubbed)


def test_long_account_or_meter_number_is_scrubbed():
    text = "Verified against meter number 8817263540 and closed the ticket."
    scrubbed = scrub_text(text)
    assert "8817263540" not in scrubbed


def test_known_customer_name_is_scrubbed():
    text = "Spoke with Rehana Bibi and confirmed the meter was replaced."
    scrubbed = scrub_text(text, customer_name="Rehana Bibi")
    assert "Rehana Bibi" not in scrubbed
    assert "confirmed the meter was replaced" in scrubbed


def test_clean_text_passes_through_unchanged_besides_name():
    text = "Reissued a corrected duplicate bill after verifying the dispute."
    assert scrub_text(text) == text
    assert not contains_pii(text)


def test_multiple_pii_types_in_one_note_all_scrubbed():
    text = "Called Ahmed at 03211234567 (ahmed@example.com, CNIC 35202-1234567-1, meter 9988776655) to confirm."
    scrubbed = scrub_text(text, customer_name="Ahmed")
    assert not contains_pii(scrubbed)
    assert "Ahmed" not in scrubbed


def test_empty_or_none_input_never_raises():
    assert scrub_text(None) == ""
    assert scrub_text("") == ""
    assert contains_pii("") is False
