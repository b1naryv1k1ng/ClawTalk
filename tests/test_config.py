import tempfile
import unittest
from pathlib import Path

from clawtalk.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_parses_stt_fields(self) -> None:
        config_text = """
transport = "gateway"
ssh_target = "eitri-openclaw"
gateway_url = "http://100.64.0.10:8080"
gateway_token = "super-secret-token"
gateway_agent = "saga"
gateway_timeout_seconds = 45
stt_backend = "placeholder"
whisper_model_size = "tiny"
whisper_device = "cpu"
whisper_compute_type = "int8"
auto_transcribe_after_recording = true
auto_send_after_transcription = true
push_to_talk_hotkey = "ctrl+shift+f9"
input_device_index = 33
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "clawtalk.toml"
            config_path.write_text(config_text, encoding="utf-8")
            config = load_config(config_path)

        self.assertEqual(config.transport, "gateway")
        self.assertEqual(config.stt_backend, "placeholder")
        self.assertEqual(config.whisper_model_size, "tiny")
        self.assertEqual(config.whisper_device, "cpu")
        self.assertEqual(config.whisper_compute_type, "int8")
        self.assertTrue(config.auto_transcribe_after_recording)
        self.assertTrue(config.auto_send_after_transcription)
        self.assertEqual(config.push_to_talk_hotkey, "ctrl+shift+f9")
        self.assertEqual(config.input_device_index, 33)
        self.assertEqual(config.gateway_url, "http://100.64.0.10:8080")
        self.assertEqual(config.gateway_token, "super-secret-token")
        self.assertEqual(config.gateway_agent, "saga")
        self.assertEqual(config.gateway_timeout_seconds, 45)


if __name__ == "__main__":
    unittest.main()
