import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from clawtalk.config import AppConfig
from clawtalk.tts import OpenAITTS, TTSError, WindowsTTS, create_tts_backend
from clawtalk.tts.openai_tts import (
    build_openai_tts_request,
    get_openai_api_key,
    request_openai_tts_audio,
)


class _FakeHTTPResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TTSTests(unittest.TestCase):
    def test_create_tts_backend_defaults_to_windows(self) -> None:
        backend = create_tts_backend(AppConfig())
        self.assertIsInstance(backend, WindowsTTS)

    def test_create_tts_backend_selects_openai(self) -> None:
        backend = create_tts_backend(AppConfig(tts_backend="openai"))
        self.assertIsInstance(backend, OpenAITTS)

    def test_get_openai_api_key_raises_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TTSError) as context:
                get_openai_api_key("OPENAI_API_KEY")
        self.assertIn("OPENAI_API_KEY", str(context.exception))

    def test_build_openai_tts_request_sets_expected_payload(self) -> None:
        request = build_openai_tts_request(
            api_key="secret-key",
            model="gpt-4o-mini-tts",
            voice="sage",
            audio_format="wav",
            text="Hello from ClawTalk.",
        )
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-4o-mini-tts")
        self.assertEqual(payload["voice"], "sage")
        self.assertEqual(payload["input"], "Hello from ClawTalk.")
        self.assertEqual(payload["response_format"], "wav")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")

    def test_request_openai_tts_audio_returns_audio_bytes(self) -> None:
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse(b"RIFF....WAVE", status=200),
        ):
            audio_bytes = request_openai_tts_audio(
                api_key="secret-key",
                model="gpt-4o-mini-tts",
                voice="sage",
                audio_format="wav",
                text="Hello from ClawTalk.",
                timeout_seconds=60,
            )
        self.assertEqual(audio_bytes, b"RIFF....WAVE")

    def test_request_openai_tts_audio_maps_auth_failure(self) -> None:
        error = urllib.error.HTTPError(
            url="https://api.openai.com/v1/audio/speech",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"invalid api key"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(TTSError) as context:
                request_openai_tts_audio(
                    api_key="secret-key",
                    model="gpt-4o-mini-tts",
                    voice="sage",
                    audio_format="wav",
                    text="Hello from ClawTalk.",
                    timeout_seconds=60,
                )
        self.assertIn("authentication failed", str(context.exception).lower())


if __name__ == "__main__":
    unittest.main()
