"""
Feature C point 5 — intent routing (dev-mode keyword heuristic, since
MISTRAL_API_KEY is unset in this environment; classify_intent() falls back
to _keyword_intent() automatically). Includes the two real ordering bugs a
live test caught and fixed — see intent.py's module comments for the
"how do I report a wrong bill?" and out-of-scope cases.
"""
from rag.intent import classify_intent, COMPLAINT_INTENT, QUESTION_INTENT, SMALLTALK_INTENT


def test_clear_complaint_statements():
    assert classify_intent("There is no electricity in my area since morning") == COMPLAINT_INTENT
    assert classify_intent("My meter is sparking and making noise") == COMPLAINT_INTENT
    assert classify_intent("Someone stole electricity by an illegal connection next door") == COMPLAINT_INTENT
    assert classify_intent("Bijli nahi hai hamare ghar mein") == COMPLAINT_INTENT


def test_process_questions_are_not_misrouted_to_complaint():
    # Regression: "wrong bill" is a complaint keyword, but this is a process
    # question, not a report — caught by a live test before the fix.
    assert classify_intent("How do I report a wrong bill?") == QUESTION_INTENT
    assert classify_intent("What is the process to file a complaint?") == QUESTION_INTENT
    assert classify_intent("Can I pay my bill online?") == QUESTION_INTENT
    assert classify_intent("Is there a way to check my bill history?") == QUESTION_INTENT


def test_smalltalk():
    assert classify_intent("Hello!") == SMALLTALK_INTENT
    assert classify_intent("thanks a lot") == SMALLTALK_INTENT
    assert classify_intent("good morning") == SMALLTALK_INTENT


def test_smalltalk_greeting_followed_by_a_real_complaint_is_not_smalltalk():
    # A short smalltalk-looking opener with a real problem attached must
    # not get swallowed as pure smalltalk.
    assert classify_intent("Hi, there has been no electricity since noon in my area") == COMPLAINT_INTENT


def test_weak_question_starters_only_apply_when_no_complaint_keyword_present():
    assert classify_intent("Why do bills arrive late sometimes?") == QUESTION_INTENT
    # "no electricity" is a strong complaint signal even with a question mark.
    assert classify_intent("Why is there no electricity in my area??") == COMPLAINT_INTENT


def test_ambiguous_short_text_defaults_to_complaint_not_silence():
    # VEMA's core job is complaint intake; an unclear utterance should still
    # reach the classifier/clarifying-question path, not a dead end.
    assert classify_intent("bijli ka masla hai") == COMPLAINT_INTENT
