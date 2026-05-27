from __future__ import annotations

from clawtalk.logging_setup import configure_logging
from clawtalk.recorder import AudioRecorder, RecorderError, format_audio_device


def main() -> None:
    configure_logging()
    recorder = AudioRecorder()
    try:
        devices = recorder.get_available_input_devices()
    except RecorderError as exc:
        print(f"Recorder error: {exc}")
        return

    if not devices:
        print("No input devices found.")
        return

    print("Available input devices:")
    for device in devices:
        print(f"  {format_audio_device(device)}")


if __name__ == "__main__":
    main()
