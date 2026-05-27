import unittest

from clawtalk.ui.main_window import (
    format_conversation_log_entry,
    format_transcript_entry,
    should_show_debug_controls,
)


class UIHelpersTests(unittest.TestCase):
    def test_format_transcript_entry_single_line(self) -> None:
        entry = format_transcript_entry("Me", "Hello there.")
        self.assertEqual(entry, "Me: Hello there.\n\n")

    def test_format_transcript_entry_multi_line(self) -> None:
        entry = format_transcript_entry("Saga", "Line one.\nLine two.")
        self.assertEqual(entry, "Saga: Line one.\nLine two.\n\n")

    def test_format_conversation_log_entry_single_line(self) -> None:
        entry = format_conversation_log_entry(
            "2026-05-27 09:00:00", "SYSTEM", "Ready."
        )
        self.assertEqual(
            entry,
            "[2026-05-27 09:00:00] SYSTEM:\n  Ready.\n\n",
        )

    def test_should_show_debug_controls_reflects_toggle(self) -> None:
        self.assertTrue(should_show_debug_controls(True))
        self.assertFalse(should_show_debug_controls(False))


if __name__ == "__main__":
    unittest.main()
