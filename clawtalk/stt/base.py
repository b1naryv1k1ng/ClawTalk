from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


class STTError(Exception):
    pass


@dataclass
class STTResult:
    transcript_text: str
    duration_seconds: float
    backend_name: str
    model_name: Optional[str] = None
    device: Optional[str] = None
    compute_type: Optional[str] = None
    transcription_time_seconds: Optional[float] = None
    model_load_time_seconds: Optional[float] = None
    diagnostics: List[str] = field(default_factory=list)


class STTBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> STTResult:
        raise NotImplementedError
