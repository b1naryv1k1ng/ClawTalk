from __future__ import annotations

import json
import logging
import os
import queue
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from clawtalk.config import AppConfig
from clawtalk.tts.base import TTSBackend, TTSError
from clawtalk.tts.windows_tts import WindowsTTS


logger = logging.getLogger(__name__)


class OpenAITTS(TTSBackend):
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._started = False
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._fallback_backend: Optional[WindowsTTS] = None

        if self._config.openai_tts_fallback_to_windows:
            self._fallback_backend = WindowsTTS()

    @property
    def backend_name(self) -> str:
        return "openai"

    def set_error_handler(self, handler: Callable[[str], None]) -> None:
        self._on_error = handler
        if self._fallback_backend is not None:
            self._fallback_backend.set_error_handler(handler)

    def set_completion_handler(self, handler: Callable[[], None]) -> None:
        self._on_complete = handler
        if self._fallback_backend is not None:
            self._fallback_backend.set_completion_handler(handler)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread.start()
            if self._fallback_backend is not None:
                self._fallback_backend.start()

    def speak_async(self, text: str) -> None:
        cleaned_text = text.strip()
        if not cleaned_text:
            logger.info("OpenAI TTS skipped because text was empty after stripping.")
            return
        if not self._started:
            self.start()
        logger.info(
            "OpenAI TTS request queued. text_length=%s model=%s voice=%s format=%s",
            len(cleaned_text),
            self._config.openai_tts_model,
            self._config.openai_tts_voice,
            self._config.openai_tts_format,
        )
        self._queue.put(cleaned_text)

    def stop(self) -> None:
        if not self._started:
            return
        logger.info("Stopping OpenAI TTS worker.")
        self._shutdown_event.set()
        self._stop_playback()
        self._queue.put(None)
        self._thread.join(timeout=2)
        if self._fallback_backend is not None:
            self._fallback_backend.stop()

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        done = threading.Event()

        def waiter() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=waiter, daemon=True).start()
        return done.wait(timeout)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    logger.info("OpenAI TTS worker received stop signal.")
                    return
                self._speak_once(item)
            finally:
                self._queue.task_done()

    def _speak_once(self, text: str) -> None:
        logger.info(
            "OpenAI TTS started. text_length=%s model=%s voice=%s format=%s",
            len(text),
            self._config.openai_tts_model,
            self._config.openai_tts_voice,
            self._config.openai_tts_format,
        )
        try:
            api_key = get_openai_api_key(self._config.openai_tts_api_key_env)
            audio_bytes = request_openai_tts_audio(
                api_key=api_key,
                model=self._config.openai_tts_model,
                voice=self._config.openai_tts_voice,
                audio_format=self._config.openai_tts_format,
                text=text,
                timeout_seconds=self._config.openai_tts_timeout_seconds,
            )
            audio_path = save_openai_tts_audio(audio_bytes, self._config.openai_tts_format)
            cleanup_old_openai_tts_files(audio_path.parent)
            self._play_audio_file(audio_path)
            logger.info("OpenAI TTS completed. text_length=%s", len(text))
            self._emit_complete()
        except Exception as exc:  # pragma: no cover
            logger.exception("OpenAI TTS failed.")
            if self._fallback_backend is not None:
                logger.warning("OpenAI TTS failed; falling back to Windows TTS.")
                self._fallback_backend.speak_async(text)
                return
            self._emit_error(f"OpenAI TTS failed: {exc}")

    def _play_audio_file(self, audio_path: Path) -> None:
        try:
            import pygame
        except ImportError as exc:  # pragma: no cover
            raise TTSError(
                "Audio playback dependency 'pygame' is missing. Reinstall requirements."
            ) from exc

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._shutdown_event.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.1)
        except Exception as exc:
            raise TTSError(f"Audio playback failed: {exc}") from exc

    def _stop_playback(self) -> None:
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            logger.exception("OpenAI TTS playback stop failed.")

    def _emit_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _emit_complete(self) -> None:
        if self._on_complete is not None:
            self._on_complete()


def get_openai_api_key(env_var_name: str) -> str:
    value = os.getenv(env_var_name.strip())
    if value and value.strip():
        return value.strip()
    raise TTSError(
        f"OpenAI TTS API key is missing. Set the {env_var_name} environment variable."
    )


def build_openai_tts_request(
    api_key: str,
    model: str,
    voice: str,
    audio_format: str,
    text: str,
) -> urllib.request.Request:
    payload = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": audio_format,
    }
    return urllib.request.Request(
        url="https://api.openai.com/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )


def request_openai_tts_audio(
    api_key: str,
    model: str,
    voice: str,
    audio_format: str,
    text: str,
    timeout_seconds: float,
) -> bytes:
    if not text.strip():
        raise TTSError("OpenAI TTS text was empty.")

    request = build_openai_tts_request(
        api_key=api_key,
        model=model,
        voice=voice,
        audio_format=audio_format,
        text=text,
    )
    logger.info(
        "OpenAI TTS request starting. model=%s voice=%s format=%s text_length=%s auth=%s",
        model,
        voice,
        audio_format,
        len(text),
        "Bearer <redacted>",
    )
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            audio_bytes = response.read()
            status_code = getattr(response, "status", response.getcode())
    except urllib.error.HTTPError as exc:
        body = read_error_body(exc)
        raise TTSError(map_openai_http_error(exc.code, body)) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
            raise TTSError(
                f"OpenAI TTS request timed out after {timeout_seconds:.0f} seconds."
            ) from exc
        raise TTSError(f"OpenAI TTS request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise TTSError(
            f"OpenAI TTS request timed out after {timeout_seconds:.0f} seconds."
        ) from exc
    except socket.timeout as exc:
        raise TTSError(
            f"OpenAI TTS request timed out after {timeout_seconds:.0f} seconds."
        ) from exc

    duration = time.perf_counter() - started_at
    logger.info(
        "OpenAI TTS request completed. status=%s duration=%.3fs audio_bytes=%s",
        status_code,
        duration,
        len(audio_bytes),
    )
    if not audio_bytes:
        raise TTSError("OpenAI TTS returned empty audio.")
    return audio_bytes


def save_openai_tts_audio(audio_bytes: bytes, audio_format: str) -> Path:
    temp_dir = Path(tempfile.gettempdir())
    suffix = ".wav" if audio_format.lower() == "wav" else ".mp3"
    with tempfile.NamedTemporaryFile(
        prefix="clawtalk_openai_tts_",
        suffix=suffix,
        delete=False,
        dir=temp_dir,
    ) as temp_file:
        temp_file.write(audio_bytes)
        return Path(temp_file.name)


def cleanup_old_openai_tts_files(directory: Path, keep_latest: int = 10) -> None:
    try:
        files = sorted(
            directory.glob("clawtalk_openai_tts_*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[keep_latest:]:
            try:
                old_file.unlink(missing_ok=True)
            except OSError:
                logger.exception("Failed to remove old OpenAI TTS temp file: %s", old_file)
    except OSError:
        logger.exception("Failed to clean up OpenAI TTS temp files.")


def read_error_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def map_openai_http_error(status_code: int, body: str) -> str:
    if status_code in {401, 403}:
        return f"OpenAI TTS authentication failed ({status_code}). Check your API key."
    if status_code == 400:
        details = extract_openai_error_message(body)
        return f"OpenAI TTS request was rejected (400): {details or 'invalid request.'}"
    if status_code == 429:
        return "OpenAI TTS rate limit reached (429). Try again in a moment."
    if status_code >= 500:
        return f"OpenAI TTS server error ({status_code}). Try again later."
    details = extract_openai_error_message(body)
    if details:
        return f"OpenAI TTS request failed ({status_code}): {details}"
    return f"OpenAI TTS request failed with HTTP {status_code}."


def extract_openai_error_message(body: str) -> str:
    if not body.strip():
        return ""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()

    if isinstance(payload, dict):
        error_value = payload.get("error")
        if isinstance(error_value, str):
            return error_value.strip()
        if isinstance(error_value, dict):
            message = error_value.get("message")
            if isinstance(message, str):
                return message.strip()
    return body.strip()
