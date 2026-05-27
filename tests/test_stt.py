import tempfile
import unittest
import wave
from pathlib import Path

from clawtalk.config import AppConfig
from clawtalk.stt import PlaceholderSTTBackend, create_stt_backend
from clawtalk.stt.base import STTError
from clawtalk.ui.main_window import format_transcription_summary


class STTTests(unittest.TestCase):
    def test_placeholder_backend_raises_clear_error(self) -> None:
        backend = PlaceholderSTTBackend()
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "test.wav"
            with wave.open(str(audio_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\x00\x00" * 10)

            with self.assertRaises(STTError):
                backend.transcribe(str(audio_path))

    def test_create_stt_backend_placeholder(self) -> None:
        config = AppConfig(stt_backend="placeholder")
        backend = create_stt_backend(config)
        self.assertIsInstance(backend, PlaceholderSTTBackend)

    def test_format_transcription_summary(self) -> None:
        from clawtalk.stt.base import STTResult

        result = STTResult(
            transcript_text="hello there",
            duration_seconds=2.5,
            backend_name="faster_whisper",
            model_name="base",
            device="cpu",
            compute_type="int8",
            transcription_time_seconds=1.2,
        )
        summary = format_transcription_summary(result)
        self.assertIn("faster_whisper", summary)
        self.assertIn("audio_duration=2.50s", summary)
        self.assertIn("transcription_time=1.20s", summary)


if __name__ == "__main__":
    unittest.main()
