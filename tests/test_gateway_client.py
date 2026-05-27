import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from clawtalk.config import AppConfig
from clawtalk.openclaw.base import OpenClawError
from clawtalk.openclaw.gateway_client import (
    OpenClawGatewayClient,
    extract_gateway_reply_text,
    summarize_gateway_models,
)


class _FakeHTTPResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class GatewayClientTests(unittest.TestCase):
    def test_extract_gateway_reply_text_returns_content(self) -> None:
        response_text = json.dumps(
            {
                "choices": [
                    {"message": {"content": 'I’m Codex — “quoted text”'}}
                ]
            },
            ensure_ascii=False,
        )
        self.assertEqual(
            extract_gateway_reply_text(response_text),
            'I’m Codex — “quoted text”',
        )

    def test_summarize_gateway_models_lists_ids(self) -> None:
        response_text = json.dumps(
            {"data": [{"id": "openclaw/saga"}, {"id": "openclaw/main"}]}
        )
        summary = summarize_gateway_models(response_text)
        self.assertIn("models=2", summary)
        self.assertIn("openclaw/saga", summary)

    def test_gateway_client_returns_reply_on_success(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
                gateway_agent="openclaw/saga",
            )
        )
        response_text = json.dumps(
            {"choices": [{"message": {"content": "Ready."}}]}
        )
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse(response_text, status=200),
        ):
            response = client.send_message_details("Say only: ready.")

        self.assertEqual(response.reply_text, "Ready.")
        self.assertEqual(response.transport_name, "gateway")
        self.assertEqual(response.return_code, 200)

    def test_gateway_client_requires_gateway_url(self) -> None:
        client = OpenClawGatewayClient(AppConfig(transport="gateway", gateway_token="secret"))
        with self.assertRaises(OpenClawError) as context:
            client.send_message_details("hello")
        self.assertIn("Gateway URL is missing", str(context.exception))

    def test_gateway_client_requires_gateway_token(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(transport="gateway", gateway_url="http://127.0.0.1:18789")
        )
        with self.assertRaises(OpenClawError) as context:
            client.send_message_details("hello")
        self.assertIn("Gateway token is missing", str(context.exception))

    def test_gateway_client_maps_auth_failure(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
            )
        )
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:18789/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"invalid token"}}'),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenClawError) as context:
                client.send_message_details("hello")
        self.assertIn("authentication failed", str(context.exception).lower())

    def test_gateway_client_maps_not_found(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
            )
        )
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:18789/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b""),
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenClawError) as context:
                client.send_message_details("hello")
        self.assertIn("/v1/chat/completions", str(context.exception))

    def test_gateway_client_rejects_non_json_response(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
            )
        )
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse("<html>not json</html>", status=200),
        ):
            with self.assertRaises(OpenClawError) as context:
                client.send_message_details("hello")
        self.assertIn("non-json", str(context.exception).lower())

    def test_gateway_client_maps_connection_refused(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
            )
        )
        error = urllib.error.URLError(ConnectionRefusedError(10061, "connection refused"))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenClawError) as context:
                client.send_message_details("hello")
        self.assertIn("connection was refused", str(context.exception).lower())

    def test_gateway_client_rejects_missing_content_shape(self) -> None:
        client = OpenClawGatewayClient(
            AppConfig(
                transport="gateway",
                gateway_url="http://127.0.0.1:18789",
                gateway_token="secret-token",
            )
        )
        response_text = json.dumps({"choices": [{}]})
        with patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResponse(response_text, status=200),
        ):
            with self.assertRaises(OpenClawError) as context:
                client.send_message_details("hello")
        self.assertIn("choices[0].message.content", str(context.exception))


if __name__ == "__main__":
    unittest.main()
