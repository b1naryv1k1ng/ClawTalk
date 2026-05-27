from __future__ import annotations

import ctypes
import logging
import platform
import time
import wave
from pathlib import Path
from typing import Optional

from clawtalk.stt.base import STTBackend, STTError, STTResult


logger = logging.getLogger(__name__)


class FasterWhisperBackend(STTBackend):
    backend_name = "faster_whisper"

    def __init__(
        self,
        model_name: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self.model_name = model_name
        self.requested_device = device
        self.requested_compute_type = compute_type
        self._model = None
        self._resolved_device: Optional[str] = None
        self._resolved_compute_type: Optional[str] = None
        self._model_load_time_seconds: Optional[float] = None

    def transcribe(self, audio_path: str) -> STTResult:
        path = Path(audio_path)
        if not path.exists():
            raise STTError(f"Audio file not found: {path}")

        model = self._load_model()
        started_at = time.perf_counter()
        try:
            segments, info = model.transcribe(str(path), vad_filter=True)
            transcript_text = " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            )
        except Exception as exc:
            raise STTError(f"faster-whisper transcription failed: {exc}") from exc

        transcription_time_seconds = time.perf_counter() - started_at
        diagnostics = []
        language = getattr(info, "language", None)
        language_probability = getattr(info, "language_probability", None)
        if language:
            diagnostics.append(f"language={language}")
        if language_probability is not None:
            diagnostics.append(f"language_probability={language_probability:.2f}")
        if not transcript_text:
            diagnostics.append("No speech detected in the recording.")

        logger.info(
            "Transcription completed. backend=%s model=%s device=%s compute_type=%s duration=%.2fs transcription_time=%.2fs",
            self.backend_name,
            self.model_name,
            self._resolved_device,
            self._resolved_compute_type,
            _get_audio_duration_seconds(path),
            transcription_time_seconds,
        )
        return STTResult(
            transcript_text=transcript_text,
            duration_seconds=_get_audio_duration_seconds(path),
            backend_name=self.backend_name,
            model_name=self.model_name,
            device=self._resolved_device,
            compute_type=self._resolved_compute_type,
            transcription_time_seconds=transcription_time_seconds,
            model_load_time_seconds=self._model_load_time_seconds,
            diagnostics=diagnostics,
        )

    def _load_model(self):
        if self._model is not None:
            return self._model

        self._resolved_device = self._resolve_device()
        self._resolved_compute_type = self._resolve_compute_type(self._resolved_device)
        started_at = time.perf_counter()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise STTError(
                "The 'faster-whisper' package is not installed. Run pip install -r requirements.txt."
            ) from exc

        logger.info(
            "Loading faster-whisper model. model=%s device=%s compute_type=%s",
            self.model_name,
            self._resolved_device,
            self._resolved_compute_type,
        )
        try:
            self._model = WhisperModel(
                self.model_name,
                device=self._resolved_device,
                compute_type=self._resolved_compute_type,
            )
        except Exception as exc:
            raise STTError(f"Could not load faster-whisper model: {exc}") from exc

        self._model_load_time_seconds = time.perf_counter() - started_at
        logger.info(
            "Loaded faster-whisper model in %.2fs",
            self._model_load_time_seconds,
        )
        return self._model

    def _resolve_device(self) -> str:
        if self.requested_device != "auto":
            return self.requested_device
        return "cuda" if _cuda_available() else "cpu"

    def _resolve_compute_type(self, device: str) -> str:
        if self.requested_compute_type != "auto":
            return self.requested_compute_type
        return "float16" if device == "cuda" else "int8"


def _get_audio_duration_seconds(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        if frame_rate <= 0:
            return 0.0
        return wav_file.getnframes() / float(frame_rate)


def _cuda_available() -> bool:
    candidates = []
    system = platform.system().lower()
    if system == "windows":
        candidates = ["nvcuda.dll"]
    elif system == "linux":
        candidates = ["libcuda.so", "libcuda.so.1"]

    for library_name in candidates:
        try:
            ctypes.CDLL(library_name)
            return True
        except OSError:
            continue
    return False
