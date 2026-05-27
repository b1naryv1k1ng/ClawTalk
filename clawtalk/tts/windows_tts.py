from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional


logger = logging.getLogger(__name__)


class WindowsTTS:
    def __init__(self) -> None:
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._started = False
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._lock = threading.Lock()

    def set_error_handler(self, handler: Callable[[str], None]) -> None:
        self._on_error = handler

    def set_completion_handler(self, handler: Callable[[], None]) -> None:
        self._on_complete = handler

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread.start()

    def speak_async(self, text: str) -> None:
        cleaned_text = text.strip()
        if not cleaned_text:
            logger.info("TTS skipped because text was empty after stripping.")
            return
        if not self._started:
            self.start()
        logger.info("TTS request queued. text_length=%s", len(cleaned_text))
        self._queue.put(cleaned_text)

    def stop(self) -> None:
        if not self._started:
            return
        logger.info("Stopping TTS worker.")
        self._queue.put(None)
        self._thread.join(timeout=2)

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
                    logger.info("TTS worker received stop signal.")
                    return
                self._speak_once(item)
            finally:
                self._queue.task_done()

    def _speak_once(self, text: str) -> None:
        logger.info("TTS playback started. text_length=%s", len(text))
        engine = None
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            logger.info("TTS playback completed. text_length=%s", len(text))
            self._emit_complete()
        except Exception as exc:  # pragma: no cover
            logger.exception("TTS playback failed.")
            self._emit_error(f"TTS playback failed: {exc}")
        finally:
            if engine is not None:
                try:
                    engine.stop()
                except Exception:
                    logger.exception("TTS engine stop failed.")

    def _emit_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _emit_complete(self) -> None:
        if self._on_complete is not None:
            self._on_complete()
