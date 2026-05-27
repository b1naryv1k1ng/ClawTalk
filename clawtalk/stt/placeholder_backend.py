from __future__ import annotations

from pathlib import Path

from clawtalk.stt.base import STTBackend, STTError, STTResult


class PlaceholderSTTBackend(STTBackend):
    backend_name = "placeholder"

    def transcribe(self, audio_path: str) -> STTResult:
        path = Path(audio_path)
        if not path.exists():
            raise STTError(f"Audio file not found: {path}")
        raise STTError(
            "Speech-to-text is not enabled. Set stt_backend = \"faster_whisper\" to transcribe recordings."
        )
