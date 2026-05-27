from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from clawtalk.config import AppConfig
from clawtalk.openclaw.base import OpenClawClient, OpenClawError, OpenClawResponse


logger = logging.getLogger(__name__)


class OpenClawGatewayClient(OpenClawClient):
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def send_message_details(self, message: str) -> OpenClawResponse:
        sanitized_message = message.strip()
        if not sanitized_message:
            raise OpenClawError("Message is empty.")

        request_url = build_gateway_endpoint_url(
            self._config.gateway_url, "/v1/chat/completions"
        )
        gateway_token = self._config.gateway_token.strip()
        if not request_url:
            raise OpenClawError("Gateway URL is missing. Set gateway_url in clawtalk.toml.")
        if not gateway_token:
            raise OpenClawError(
                "Gateway token is missing. Set gateway_token in clawtalk.toml."
            )

        payload = build_gateway_chat_payload(
            resolve_gateway_agent(self._config),
            sanitized_message,
        )
        response_text, status_code, started_at, ended_at = perform_gateway_request(
            url=request_url,
            token=gateway_token,
            payload=payload,
            timeout_seconds=self._config.gateway_timeout_seconds,
        )
        reply_text = extract_gateway_reply_text(response_text)
        if not reply_text:
            raise OpenClawError("Gateway returned an empty reply.")

        return OpenClawResponse(
            reply_text=reply_text,
            transport_name="gateway",
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=ended_at - started_at,
            return_code=status_code,
            output_length=len(response_text),
            error_length=0,
        )


def resolve_gateway_agent(config: AppConfig) -> str:
    agent = config.gateway_agent.strip()
    if agent:
        return agent
    fallback_agent = config.openclaw_agent.strip()
    if fallback_agent:
        return fallback_agent
    raise OpenClawError("Gateway agent is missing. Set gateway_agent or openclaw_agent.")


def build_gateway_endpoint_url(base_url: str, path: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base}{normalized_path}"


def build_gateway_chat_payload(model: str, message: str) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "user": "clawtalk",
    }


def build_gateway_request(
    url: str,
    token: str,
    payload: Optional[Dict[str, Any]],
) -> urllib.request.Request:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    return urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )


def perform_gateway_request(
    url: str,
    token: str,
    payload: Optional[Dict[str, Any]],
    timeout_seconds: float,
) -> tuple[str, int, float, float]:
    request = build_gateway_request(url, token, payload)
    logger.info(
        "Gateway request starting. url=%s timeout_seconds=%s method=%s auth=%s",
        url,
        timeout_seconds,
        request.get_method(),
        "Bearer <redacted>",
    )
    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_bytes = response.read()
            status_code = getattr(response, "status", response.getcode())
    except urllib.error.HTTPError as exc:
        ended_at = time.perf_counter()
        error_text = read_http_error_body(exc)
        logger.warning(
            "Gateway HTTP error. url=%s status=%s duration=%.3fs body_length=%s",
            url,
            exc.code,
            ended_at - started_at,
            len(error_text),
        )
        raise map_gateway_http_error(exc.code, error_text) from exc
    except urllib.error.URLError as exc:
        ended_at = time.perf_counter()
        logger.warning(
            "Gateway connection error. url=%s duration=%.3fs reason=%s",
            url,
            ended_at - started_at,
            exc.reason,
        )
        raise map_gateway_url_error(exc) from exc
    except TimeoutError as exc:
        ended_at = time.perf_counter()
        logger.warning(
            "Gateway timeout. url=%s duration=%.3fs timeout_seconds=%s",
            url,
            ended_at - started_at,
            timeout_seconds,
        )
        raise OpenClawError(
            f"Gateway request timed out after {timeout_seconds:.0f} seconds."
        ) from exc
    except socket.timeout as exc:
        ended_at = time.perf_counter()
        logger.warning(
            "Gateway socket timeout. url=%s duration=%.3fs timeout_seconds=%s",
            url,
            ended_at - started_at,
            timeout_seconds,
        )
        raise OpenClawError(
            f"Gateway request timed out after {timeout_seconds:.0f} seconds."
        ) from exc
    ended_at = time.perf_counter()

    response_text = decode_gateway_bytes(response_bytes)
    logger.info(
        "Gateway request completed. url=%s status=%s duration=%.3fs response_length=%s",
        url,
        status_code,
        ended_at - started_at,
        len(response_text),
    )
    logger.debug("Gateway response body: %s", response_text)
    return response_text, status_code, started_at, ended_at


def decode_gateway_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def read_http_error_body(error: urllib.error.HTTPError) -> str:
    try:
        return decode_gateway_bytes(error.read())
    except Exception:
        return ""


def parse_gateway_json(response_text: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise OpenClawError("Gateway returned a non-JSON response.") from exc
    if not isinstance(parsed, dict):
        raise OpenClawError("Gateway returned an unexpected JSON response.")
    return parsed


def extract_gateway_reply_text(response_text: str) -> str:
    payload = parse_gateway_json(response_text)
    try:
        choices = payload["choices"]
        first_choice = choices[0]
        message = first_choice["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenClawError(
            "Gateway JSON response did not include choices[0].message.content."
        ) from exc
    if not isinstance(content, str):
        raise OpenClawError(
            "Gateway JSON response did not include a text message content string."
        )
    return content.strip()


def summarize_gateway_models(response_text: str) -> str:
    payload = parse_gateway_json(response_text)
    models = payload.get("data")
    if not isinstance(models, list):
        raise OpenClawError("Gateway /v1/models response did not include a data list.")
    model_ids: List[str] = []
    for item in models:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id.strip():
                model_ids.append(model_id.strip())
    if not model_ids:
        return "models=0"
    preview = ", ".join(model_ids[:5])
    if len(model_ids) > 5:
        preview = f"{preview}, ..."
    return f"models={len(model_ids)} [{preview}]"


def map_gateway_http_error(status_code: int, error_text: str) -> OpenClawError:
    details = extract_gateway_error_message(error_text)
    if status_code in {401, 403}:
        return OpenClawError(
            f"Gateway authentication failed ({status_code}). Check gateway_token."
        )
    if status_code == 404:
        return OpenClawError(
            "Gateway endpoint was not found (404). Confirm /v1/chat/completions is enabled."
        )
    if details:
        return OpenClawError(f"Gateway request failed ({status_code}): {details}")
    return OpenClawError(f"Gateway request failed with HTTP {status_code}.")


def extract_gateway_error_message(error_text: str) -> str:
    if not error_text.strip():
        return ""
    try:
        payload = parse_gateway_json(error_text)
    except OpenClawError:
        return error_text.strip()

    error_value = payload.get("error")
    if isinstance(error_value, str):
        return error_value.strip()
    if isinstance(error_value, dict):
        message = error_value.get("message")
        if isinstance(message, str):
            return message.strip()
    message = payload.get("message")
    if isinstance(message, str):
        return message.strip()
    return error_text.strip()


def map_gateway_url_error(error: urllib.error.URLError) -> OpenClawError:
    reason = getattr(error, "reason", None)
    if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout):
        return OpenClawError("Gateway request timed out.")
    if isinstance(reason, ConnectionRefusedError):
        return OpenClawError(
            "Gateway connection was refused. Confirm the Gateway is running and reachable."
        )
    if isinstance(reason, OSError):
        reason_text = str(reason)
        if "10061" in reason_text or "61" in reason_text:
            return OpenClawError(
                "Gateway connection was refused. Confirm the Gateway is running and reachable."
            )
    return OpenClawError(f"Could not connect to Gateway: {reason}")
