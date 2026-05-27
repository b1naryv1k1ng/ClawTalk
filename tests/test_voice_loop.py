import unittest
from pathlib import Path

from clawtalk.recorder import RecordingResult, RecordingStats
from clawtalk.stt.base import STTResult
from clawtalk.ui.main_window import (
    should_auto_send_transcript,
    should_auto_transcribe_recording,
)


class VoiceLoopTests(unittest.TestCase):
    def _recording(self, silent: bool) -> RecordingResult:
        return RecordingResult(
            file_path=Path("C:/tmp/test.wav"),
            duration_seconds=1.0,
            file_size_bytes=100,
            device_index=1,
            device_name="Mic",
            stats=RecordingStats(
                peak_amplitude=0 if silent else 100,
                rms_level=0 if silent else 50,
                appears_silent=silent,
            ),
        )

    def test_should_auto_transcribe_respects_toggle(self) -> None:
        self.assertTrue(should_auto_transcribe_recording(True, self._recording(False)))
        self.assertFalse(should_auto_transcribe_recording(False, self._recording(False)))

    def test_should_auto_transcribe_requires_recording(self) -> None:
        self.assertFalse(should_auto_transcribe_recording(True, None))

    def test_should_auto_send_rejects_empty_transcript(self) -> None:
        result = STTResult(transcript_text="   ", duration_seconds=1.0, backend_name="fw")
        should_send, reason = should_auto_send_transcript(True, self._recording(False), result)
        self.assertFalse(should_send)
        self.assertIn("empty", reason.lower())

    def test_should_auto_send_rejects_silent_recording(self) -> None:
        result = STTResult(transcript_text="hello", duration_seconds=1.0, backend_name="fw")
        should_send, reason = should_auto_send_transcript(True, self._recording(True), result)
        self.assertFalse(should_send)
        self.assertIn("silent", reason.lower())

    def test_should_auto_send_rejects_when_disabled(self) -> None:
        result = STTResult(transcript_text="hello", duration_seconds=1.0, backend_name="fw")
        should_send, reason = should_auto_send_transcript(False, self._recording(False), result)
        self.assertFalse(should_send)
        self.assertIn("disabled", reason.lower())

    def test_should_auto_send_accepts_valid_transcript(self) -> None:
        result = STTResult(transcript_text="hello", duration_seconds=1.0, backend_name="fw")
        should_send, reason = should_auto_send_transcript(True, self._recording(False), result)
        self.assertTrue(should_send)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
