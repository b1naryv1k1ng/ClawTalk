from clawtalk.config import AppConfig
from clawtalk.stt.base import STTBackend, STTError, STTResult
from clawtalk.stt.faster_whisper_backend import FasterWhisperBackend
from clawtalk.stt.placeholder_backend import PlaceholderSTTBackend


def create_stt_backend(config: AppConfig) -> STTBackend:
    if config.stt_backend == "faster_whisper":
        return FasterWhisperBackend(
            model_name=config.whisper_model_size,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
    if config.stt_backend == "placeholder":
        return PlaceholderSTTBackend()
    raise STTError(f"Unsupported STT backend: {config.stt_backend}")


__all__ = [
    "STTBackend",
    "STTError",
    "STTResult",
    "PlaceholderSTTBackend",
    "FasterWhisperBackend",
    "create_stt_backend",
]
