"""
Feature A — echo guard. See echo_guard.py's module docstring for the rule:
a generated reply must never open by restating the customer's own words.
"""
from echo_guard import strip_echo, find_echo_split


def test_exact_echo_is_fully_stripped():
    transcript = "there is no electricity in my area since this morning"
    reply = "There is no electricity in my area since this morning."
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is True
    assert cleaned == ""  # nothing but the echo — caller must regenerate/fallback


def test_echo_phrase_prefix_is_stripped_and_real_answer_survives():
    transcript = "my bill is way too high this month"
    reply = (
        "You said your bill is way too high this month. "
        "I've logged this as a billing dispute — a representative will review "
        "your meter reading within two business days."
    )
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is True
    assert "logged this as a billing dispute" in cleaned
    assert "you said" not in cleaned.lower()


def test_partial_leading_echo_is_stripped():
    transcript = "the transformer near my house is sparking"
    reply = (
        "I heard the transformer near your house is sparking. "
        "Please stay away from it — a technician has been dispatched."
    )
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is True
    assert cleaned.startswith("Please stay away")


def test_legitimate_reply_sharing_keywords_is_not_stripped():
    # Shares "transformer" and "sparking" with a hypothetical transcript but
    # is genuinely new content, not a restatement — must survive untouched.
    transcript = "the transformer near my house is sparking"
    reply = (
        "Sparking transformers are a safety hazard — please keep at least "
        "ten meters away and do not touch any exposed wiring."
    )
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is False
    assert cleaned == reply


def test_short_unrelated_reply_is_not_flagged():
    transcript = "when will my new connection be ready"
    reply = "New connections are typically processed within 7-10 business days."
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is False
    assert cleaned == reply


def test_empty_transcript_or_reply_never_flagged():
    assert strip_echo("Some reply.", "") == ("Some reply.", False)
    assert strip_echo("", "some transcript") == ("", False)
    assert find_echo_split("reply", "") is None
    assert find_echo_split("", "transcript") is None


def test_bare_echo_phrase_with_nothing_after_is_consumed():
    transcript = "no power since noon"
    reply = "You said. We are on it and will update you shortly."
    cleaned, fired = strip_echo(reply, transcript)
    assert fired is True
    assert "We are on it" in cleaned
