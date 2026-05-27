from __future__ import annotations

from clawtalk.logging_setup import configure_logging
from clawtalk.tts.windows_tts import WindowsTTS


def main() -> None:
    configure_logging()
    tts = WindowsTTS()
    tts.set_error_handler(lambda message: print(f"TTS error: {message}"))
    tts.speak_async("ClawTalk test one.")
    tts.speak_async("ClawTalk test two.")
    tts.speak_async("ClawTalk test three.")
    tts.wait_until_idle(timeout=30)
    tts.stop()


if __name__ == "__main__":
    main()
