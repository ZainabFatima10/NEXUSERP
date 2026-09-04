"""
NEXUS ERP — VEMA Text-to-Speech (local Kokoro)
Per the VEMA pipeline doc's cost table, this project uses local Kokoro
(not gTTS/Edge-TTS/Google Cloud TTS). Lazily loads the model on first use.

Dev-mode fallback (kokoro package/model unavailable): returns
audio_available=False and the caller (customer portal) just shows the text
reply instead of playing audio — the voice agent still functions push-to-talk
over REST, it just degrades to text-only when Kokoro isn't installed.
"""
import os
import base64

KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")

_pipeline = None
_load_attempted = False


def _get_pipeline():
    global _pipeline, _load_attempted
    if _load_attempted:
        return _pipeline
    _load_attempted = True
    try:
        from kokoro import KPipeline
        _pipeline = KPipeline(lang_code="a")  # American English
        print("[OK] Kokoro TTS pipeline loaded")
    except Exception as e:
        print(f"[WARN] Kokoro TTS unavailable ({e}) — voice replies will be text-only. "
              f"Install `kokoro` to enable audio playback.")
    return _pipeline


def synthesize(text: str) -> dict:
    """
    Returns {"audio_available": bool, "audio_base64": str|None, "sample_rate": int|None}.
    Never raises.
    """
    pipeline = _get_pipeline()
    if pipeline is None:
        return {"audio_available": False, "audio_base64": None, "sample_rate": None}

    try:
        import numpy as np
        import soundfile as sf
        import io

        chunks = []
        for _, _, audio in pipeline(text, voice=KOKORO_VOICE):
            chunks.append(audio)
        full_audio = np.concatenate(chunks) if chunks else np.zeros(0)

        buf = io.BytesIO()
        sf.write(buf, full_audio, 24000, format="WAV")
        return {
            "audio_available": True,
            "audio_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "sample_rate": 24000,
        }
    except Exception as e:
        print(f"[WARN] Kokoro synthesis failed ({e})")
        return {"audio_available": False, "audio_base64": None, "sample_rate": None}
