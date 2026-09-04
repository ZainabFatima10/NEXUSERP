"""
NEXUS ERP — VEMA Speech-to-Text (local Whisper)
Per the VEMA pipeline doc's cost table, this project uses local Whisper
(not a paid cloud STT API). Lazily loads the model on first use so a
server that never receives voice traffic doesn't pay the load cost.

Dev-mode fallback (whisper package or model weights unavailable): returns
a clear placeholder transcript instead of crashing, so the rest of the
pipeline (classification -> routing -> ticket) stays testable — mirrors
inventory_v2.py's MODEL_LOADED fallback pattern.
"""
import os
import tempfile

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

_model = None
_load_attempted = False
_load_error = None


def _get_model():
    global _model, _load_attempted, _load_error
    if _load_attempted:
        return _model
    _load_attempted = True
    try:
        import whisper  # openai-whisper
        _model = whisper.load_model(WHISPER_MODEL_SIZE)
        print(f"[OK] Whisper STT model loaded ({WHISPER_MODEL_SIZE})")
    except Exception as e:
        _load_error = str(e)
        print(f"[WARN] Whisper STT unavailable ({e}) — voice tickets will use a "
              f"placeholder transcript. Install `openai-whisper` + ffmpeg to enable.")
    return _model


def transcribe(audio_bytes: bytes, filename_hint: str = "audio.webm") -> dict:
    """
    Returns {"text": str, "engine": "whisper"|"unavailable", "language": str|None}.
    Never raises — always returns something the caller can log as a
    complaint_events 'voice_transcript' row.
    """
    model = _get_model()
    if model is None:
        return {
            "text": "[Voice transcription unavailable in this environment — "
                    "Whisper is not installed/configured. See VEMA_BACKEND_WIRING.md.]",
            "engine": "unavailable",
            "language": None,
        }

    suffix = os.path.splitext(filename_hint)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        result = model.transcribe(tmp.name, language="en")

    return {
        "text": (result.get("text") or "").strip(),
        "engine": "whisper",
        "language": result.get("language"),
    }
