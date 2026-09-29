"""
NEXUS ERP — Shared LLM Client
Used by llm_service.py, rag/generation.py, and rag/intent.py so a provider
swap happens in ONE place instead of three. Priority:

  1. Gemini  (GEMINI_API_KEY)  — free tier, no card required; the default
     recommendation for this project since Mistral's paid tier wasn't
     workable for the team.
  2. Mistral (MISTRAL_API_KEY) — kept as a fallback for anyone who already
     has a Mistral key; unchanged behavior from before this module existed.
  3. None — every caller already has its own deterministic dev-mode
     fallback (keyword classifier, canned replies, etc.) for this case.

Gemini's request/response shape is genuinely different from Mistral's
(OpenAI-style `messages` + a system-role message vs. Gemini's `contents`/
`parts` with a separate top-level `systemInstruction`) — normalized here
behind chat_text()/chat_json() so callers never see either shape directly.

Live-verified against a real Gemini key 2026-09-29: chat_text() and
chat_json() (JSON mode) both confirmed working on gemini-2.5-flash-lite.
Mistral's path remains untested (no Mistral key available).
"""
import os
import json
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# gemini-2.0-flash no longer exists on this API as of live-testing against a
# real key (2026-09-29) — gemini-2.5-flash-lite is the model that actually
# responded reliably then (gemini-flash-latest and gemini-3.8-flash both
# 503'd as overloaded). This API's model lineup moves fast; if this default
# stops working, GET /v1beta/models?key=... to see what's current.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

PROVIDER = "gemini" if GEMINI_API_KEY else ("mistral" if MISTRAL_API_KEY else "none")
if PROVIDER == "none":
    print("[WARN] No LLM provider configured (GEMINI_API_KEY / MISTRAL_API_KEY both "
          "unset) — VEMA runs on deterministic dev-mode fallbacks only.")


def _gemini_call(system_prompt: str, user_message: str, temperature: float, json_mode: bool) -> Optional[str]:
    try:
        url = GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL)
        generation_config = {"temperature": temperature}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        resp = httpx.post(
            url,
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": generation_config,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if not candidates:
            return None
        return candidates[0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"[WARN] Gemini call failed ({e})")
        return None


def _mistral_call(system_prompt: str, user_message: str, temperature: float, json_mode: bool) -> Optional[str]:
    try:
        payload = {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            MISTRAL_URL,
            headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[WARN] Mistral call failed ({e})")
        return None


def chat_text(system_prompt: str, user_message: str, temperature: float = 0.3) -> Optional[str]:
    """Free-text completion. Returns None (never raises) if no provider is
    configured, or the call fails — the caller supplies its own dev-mode
    fallback in that case, same as before this module existed."""
    if PROVIDER == "gemini":
        return _gemini_call(system_prompt, user_message, temperature, json_mode=False)
    if PROVIDER == "mistral":
        return _mistral_call(system_prompt, user_message, temperature, json_mode=False)
    return None


def chat_json(system_prompt: str, user_message: str, temperature: float = 0.1) -> Optional[dict]:
    """JSON-mode completion, pre-parsed. Returns None on failure, invalid
    JSON, or no provider configured — never raises."""
    if PROVIDER == "gemini":
        raw = _gemini_call(system_prompt, user_message, temperature, json_mode=True)
    elif PROVIDER == "mistral":
        raw = _mistral_call(system_prompt, user_message, temperature, json_mode=True)
    else:
        raw = None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[WARN] {PROVIDER} returned invalid JSON ({e})")
        return None


def is_available() -> bool:
    return PROVIDER != "none"
