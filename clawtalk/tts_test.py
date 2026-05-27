from __future__ import annotations

import sys
import threading

from clawtalk.config import ConfigError, load_config
from clawtalk.tts import TTSError, create_tts_backend


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    text = args[0] if args else "Hello, this is Saga."
    tts = None
    error_messages: list[str] = []
    completed = threading.Event()

    try:
        config = load_config()
        tts = create_tts_backend(config)
        tts.set_error_handler(lambda message: error_messages.append(message))
        tts.set_completion_handler(lambda: completed.set())
        tts.start()
        tts.speak_async(text)
        if not tts.wait_until_idle(timeout=config.openai_tts_timeout_seconds + 30):
            print("TTS test timed out waiting for playback to finish.")
            return 1
        if error_messages:
            print(f"TTS test failed: {error_messages[-1]}")
            return 1
        if not completed.is_set():
            print("TTS test finished without a completion callback.")
            return 1
        return 0
    except (ConfigError, TTSError) as exc:
        print(f"TTS test failed: {exc}")
        return 1
    finally:
        try:
            if tts is not None:
                tts.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
