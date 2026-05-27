from clawtalk.config import AppConfig
from clawtalk.tts.base import TTSBackend, TTSError
from clawtalk.tts.openai_tts import OpenAITTS
from clawtalk.tts.windows_tts import WindowsTTS


def create_tts_backend(config: AppConfig) -> TTSBackend:
    backend = config.tts_backend.strip().lower() or "windows"
    if backend == "windows":
        return WindowsTTS()
    if backend == "openai":
        return OpenAITTS(config)
    raise TTSError(
        f"Unsupported TTS backend '{config.tts_backend}'. Expected 'windows' or 'openai'."
    )


__all__ = ["TTSBackend", "TTSError", "WindowsTTS", "OpenAITTS", "create_tts_backend"]
