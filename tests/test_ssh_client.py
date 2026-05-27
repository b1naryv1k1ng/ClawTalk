import unittest

from clawtalk.openclaw.ssh_client import (
    build_openclaw_remote_command,
    normalize_ssh_output,
    resolve_ssh_target,
)


COMMAND_TEMPLATE = 'openclaw agent --agent {agent} --message {message}'


class OpenClawSSHClientTests(unittest.TestCase):
    def test_build_remote_command_with_plain_sentence(self) -> None:
        command = build_openclaw_remote_command(
            COMMAND_TEMPLATE,
            "main",
            "Say this is working in one sentence.",
        )
        self.assertEqual(
            command,
            "openclaw agent --agent main --message 'Say this is working in one sentence.'",
        )

    def test_build_remote_command_with_apostrophe(self) -> None:
        command = build_openclaw_remote_command(
            COMMAND_TEMPLATE,
            "main",
            "What's 2 + 2?",
        )
        self.assertEqual(
            command,
            "openclaw agent --agent main --message 'What'\"'\"'s 2 + 2?'",
        )

    def test_build_remote_command_with_double_quotes(self) -> None:
        command = build_openclaw_remote_command(
            COMMAND_TEMPLATE,
            "main",
            'Say exactly: "hello from ClawTalk"',
        )
        self.assertEqual(
            command,
            'openclaw agent --agent main --message \'Say exactly: "hello from ClawTalk"\'',
        )

    def test_build_remote_command_with_newline(self) -> None:
        command = build_openclaw_remote_command(
            COMMAND_TEMPLATE,
            "main",
            "Give me a two-line response.",
        )
        self.assertEqual(
            command,
            "openclaw agent --agent main --message 'Give me a two-line response.'",
        )

    def test_resolve_ssh_target_prefers_alias(self) -> None:
        target = resolve_ssh_target("eitri-openclaw", "openclaw", "eitri")
        self.assertEqual(target, "eitri-openclaw")

    def test_resolve_ssh_target_falls_back_to_user_and_host(self) -> None:
        target = resolve_ssh_target("", "openclaw", "eitri")
        self.assertEqual(target, "openclaw@eitri")

    def test_normalize_ssh_output_preserves_utf8_smart_punctuation(self) -> None:
        text = 'I’m Codex — “quoted text”\n'
        self.assertEqual(normalize_ssh_output(text), 'I’m Codex — “quoted text”')


if __name__ == "__main__":
    unittest.main()
