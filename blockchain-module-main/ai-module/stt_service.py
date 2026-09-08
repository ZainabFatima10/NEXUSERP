"""
NEXUS ERP — VEMA Speech-to-Text (local Whisper)
Per the VEMA pipeline doc's cost table, this project uses a local Whisper
model (not a paid cloud STT API). Lazily loads the model on first use so a
server that never receives voice traffic doesn't pay the load cost.

Two local backends are supported, tried in order:
  1. faster-whisper (CTranslate2) — lightweight, no PyTorch, no system
     ffmpeg (bundles PyAV for decoding). This is the default.
  2. openai-whisper — used only if faster-whisper isn't importable but the
     `whisper` package is. Needs PyTorch + a system ffmpeg binary.

Dev-mode fallback (neither backend available / model weights can't be
fetched): returns a clear placeholder transcript instead of crashing, so
the rest of the pipeline (classification -> routing -> ticket) stays
testable — mirrors inventory_v2.py's MODEL_LOADED fallback pattern.

Accuracy knobs (env):
  WHISPER_MODEL_SIZE   default "small" — tiny/base are noticeably worse on
                       accented English; small is the demo sweet spot,
                       medium is better but ~3x slower on CPU.
  WHISPER_COMPUTE_TYPE default "int8" (faster-whisper only) — "int8_float32"
                       or "float32" trade speed for a little accuracy.
  WHISPER_LANGUAGE     default "en" — set "" to auto-detect.
Decoding is also tuned below: Silero VAD to drop silence/noise, a domain
initial_prompt to bias toward grid/DISCO vocabulary, and
condition_on_previous_text=False so short clips don't spiral into repeats.
"""
import os
import tempfile

WHISPER_MODEL_SIZE   = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_LANGUAGE     = os.getenv("WHISPER_LANGUAGE", "en") or None

# Nudges the decoder toward the words that actually show up in DISCO
# complaints — utility jargon, units, and local place names Whisper would
# otherwise mangle.
_DOMAIN_PROMPT = (
    "NEXUS ERP complaint intake. Common terms: electricity, power outage, "
    "load-shedding, transformer, feeder, grid station, PMT, meter reading, "
    "billing, overbilling, kilowatt, voltage fluctuation, tripping, "
    "WAPDA, IESCO, LESCO, DISCO, Islamabad, Rawalpindi, sector G-11, F-10."
)

_model = None            # loaded backend model (faster-whisper or openai-whisper)
_engine = None           # "faster-whisper" | "whisper"
_load_attempted = False
_load_error = None


def _get_model():
    global _model, _engine, _load_attempted, _load_error
    if _load_attempted:
        return _model
    _load_attempted = True

    # 1. faster-whisper (preferred)
    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu",
                              compute_type=WHISPER_COMPUTE_TYPE)
        _engine = "faster-whisper"
        print(f"[OK] faster-whisper STT model loaded "
              f"({WHISPER_MODEL_SIZE}, cpu/{WHISPER_COMPUTE_TYPE})")
        return _model
    except Exception as e:
        _load_error = f"faster-whisper: {e}"

    # 2. openai-whisper (fallback)
    try:
        import whisper  # openai-whisper
        _model = whisper.load_model(WHISPER_MODEL_SIZE)
        _engine = "whisper"
        print(f"[OK] Whisper STT model loaded ({WHISPER_MODEL_SIZE})")
        return _model
    except Exception as e:
        _load_error = f"{_load_error} | openai-whisper: {e}"

    print(f"[WARN] Whisper STT unavailable ({_load_error}) — voice tickets will "
          f"use a placeholder transcript. Install `faster-whisper` to enable.")
    return _model


def transcribe(audio_bytes: bytes, filename_hint: str = "audio.webm") -> dict:
    """
    Returns {"text": str, "engine": "faster-whisper"|"whisper"|"unavailable",
             "language": str|None}.
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
    # delete=False + manual unlink: Windows won't let a second handle (the
    # decoder) open an already-open NamedTemporaryFile.
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.close()

        if _engine == "faster-whisper":
            segments, info = model.transcribe(
                tmp.name,
                language=WHISPER_LANGUAGE,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                initial_prompt=_DOMAIN_PROMPT,
            )
            text = "".join(seg.text for seg in segments).strip()
            language = getattr(info, "language", None)
        else:  # openai-whisper
            result = model.transcribe(
                tmp.name,
                language=WHISPER_LANGUAGE,
                condition_on_previous_text=False,
                initial_prompt=_DOMAIN_PROMPT,
            )
            text = (result.get("text") or "").strip()
            language = result.get("language")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return {"text": text, "engine": _engine, "language": language}
