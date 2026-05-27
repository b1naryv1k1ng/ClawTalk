from __future__ import annotations

import sys
import time
from pathlib import Path

from clawtalk.config import ConfigError, load_config
from clawtalk.logging_setup import configure_logging
from clawtalk.stt import STTError, create_stt_backend


def main() -> int:
    configure_logging()
    if len(sys.argv) != 2:
        print("Usage: python -m clawtalk.stt_test PATH_TO_WAV")
        return 1

    audio_path = Path(sys.argv[1])
    try:
        config = load_config()
        backend = create_stt_backend(config)
    except (ConfigError, STTError) as exc:
        print(f"Configuration error: {exc}")
        return 1

    started_at = time.perf_counter()
    try:
        result = backend.transcribe(str(audio_path))
    except STTError as exc:
        print(f"Transcription failed: {exc}")
        return 1

    elapsed = time.perf_counter() - started_at
    print(f"Transcript: {result.transcript_text}")
    print(f"Backend: {result.backend_name}")
    print(f"Model: {result.model_name}")
    print(f"Device: {result.device}")
    print(f"Compute type: {result.compute_type}")
    print(f"Audio duration: {result.duration_seconds:.2f}s")
    if result.model_load_time_seconds is not None:
        print(f"Model load time: {result.model_load_time_seconds:.2f}s")
    if result.transcription_time_seconds is not None:
        print(f"Transcription time: {result.transcription_time_seconds:.2f}s")
    print(f"Total command time: {elapsed:.2f}s")
    if result.diagnostics:
        print("Diagnostics:")
        for item in result.diagnostics:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
