"""
NEXUS ERP — VEMA Echo Guard (Feature A)
A generated bot reply (from the LLM chat path, and later the RAG generation
path) must never open by repeating, quoting, or paraphrasing the customer's
own transcribed words back to them ("you said...", "I heard...", "so you're
saying..."). This is a post-processing safety net applied on top of the
system-prompt instruction, not a replacement for it — prompts drift, this
doesn't.

Used by llm_service.generate_chat_reply() and rag/generation.py.
"""
import re
from difflib import SequenceMatcher
from typing import Optional, Tuple

# Phrases that unambiguously signal the reply is about to restate the user's
# words, regardless of how much of the transcript actually follows.
ECHO_PHRASES = [
    "you said", "you mentioned", "you're saying", "you are saying",
    "i heard", "i understand you said", "if i understand",
    "so you're saying", "so you are saying", "to confirm, you said",
    "just to confirm you said", "just to confirm, you said",
]

_WORD_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = _WORD_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _strip_leading_echo_phrase(normalized_sentence: str) -> Optional[str]:
    """If normalized_sentence starts with a known echo phrase, return the
    remainder after it; otherwise None."""
    for phrase in ECHO_PHRASES:
        if normalized_sentence.startswith(phrase):
            return normalized_sentence[len(phrase):].strip(" :,-")
    return None


def find_echo_split(reply: str, transcript: str, threshold: float = 0.8) -> Optional[int]:
    """
    If `reply` opens with a near-copy of `transcript` (bare, or introduced by
    an echo phrase like "you said"), return the character offset into `reply`
    where the echoed portion ends. Returns None if no echo is detected at
    the start of the reply.

    Only the LEADING sentence(s) are considered — a reply that happens to
    share a few keywords with the transcript later on (e.g. repeating the
    word "transformer" while giving real guidance) must NOT be flagged; this
    only fires on a genuine restatement sitting at the very front.
    """
    if not reply or not transcript:
        return None
    norm_transcript = _normalize(transcript)
    if not norm_transcript:
        return None

    sentences = _SENTENCE_SPLIT_RE.split(reply.strip())
    consumed = 0
    matched_any = False

    for sent in sentences:
        norm_sent = _normalize(sent)
        if not norm_sent:
            consumed += len(sent) + 1
            continue

        after_phrase = _strip_leading_echo_phrase(norm_sent)
        has_echo_phrase = after_phrase is not None
        compare_target = after_phrase if has_echo_phrase else norm_sent

        if not compare_target:
            # The whole sentence WAS an echo phrase with nothing else in it
            # ("You said,") — still an echo, consume it.
            if has_echo_phrase:
                consumed += len(sent)
                while consumed < len(reply) and reply[consumed].isspace():
                    consumed += 1
                matched_any = True
                continue
            break

        ratio = _similarity(compare_target, norm_transcript)
        # A bare near-copy needs the full threshold; a sentence explicitly
        # introduced by an echo phrase is treated more leniently since the
        # phrase itself already confirms intent to restate.
        is_echo = ratio >= threshold or (has_echo_phrase and ratio >= threshold * 0.6)
        if not is_echo:
            break

        consumed += len(sent)
        while consumed < len(reply) and reply[consumed].isspace():
            consumed += 1
        matched_any = True

    return consumed if matched_any and consumed > 0 else None


def strip_echo(reply: str, transcript: str, threshold: float = 0.8) -> Tuple[str, bool]:
    """
    Returns (cleaned_reply, guard_fired). If the entire reply turns out to be
    an echo, cleaned_reply is "" — the caller must regenerate or fall back;
    never surface an empty string to the customer.
    """
    idx = find_echo_split(reply, transcript, threshold)
    if idx is None:
        return reply, False
    remainder = reply[idx:].strip()
    return remainder, True
