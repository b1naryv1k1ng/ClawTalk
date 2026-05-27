import unittest

from clawtalk.ui.main_window import format_conversation_log_entry


class UIHelpersTests(unittest.TestCase):
    def test_format_conversation_log_entry_single_line(self) -> None:
        entry = format_conversation_log_entry(
            "2026-05-27 09:00:00", "YOU", "Hello there."
        )
        self.assertEqual(
            entry,
            "[2026-05-27 09:00:00] YOU:\n  Hello there.\n\n",
        )

    def test_format_conversation_log_entry_multi_line(self) -> None:
        entry = format_conversation_log_entry(
            "2026-05-27 09:00:00", "OPENCLAW", "Line one.\nLine two."
        )
        self.assertEqual(
            entry,
            "[2026-05-27 09:00:00] OPENCLAW:\n  Line one.\n  Line two.\n\n",
        )


if __name__ == "__main__":
    unittest.main()
