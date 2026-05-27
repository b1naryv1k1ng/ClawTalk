from __future__ import annotations

from clawtalk.config import ConfigError, load_config
from clawtalk.openclaw.base import OpenClawError
from clawtalk.openclaw.gateway_client import (
    build_gateway_chat_payload,
    build_gateway_endpoint_url,
    extract_gateway_reply_text,
    perform_gateway_request,
    resolve_gateway_agent,
    summarize_gateway_models,
)


def redact_token(token: str) -> str:
    token = token.strip()
    if not token:
        return "(not set)"
    if len(token) <= 4:
        return "*" * len(token)
    return f"{token[:4]}...{len(token)} chars"


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 1

    gateway_url = config.gateway_url.strip()
    gateway_token = config.gateway_token.strip()
    gateway_agent = resolve_gateway_agent(config)

    print(f"transport={config.transport or 'ssh'}")
    print(f"gateway_url={gateway_url or '(not set)'}")
    print(f"gateway_token={redact_token(gateway_token)}")
    print(f"gateway_agent={gateway_agent}")
    print(f"gateway_timeout_seconds={config.gateway_timeout_seconds}")

    if not gateway_url:
        print("Gateway URL is missing.")
        return 1
    if not gateway_token:
        print("Gateway token is missing.")
        return 1

    try:
        models_response, models_status, models_started, models_ended = perform_gateway_request(
            url=build_gateway_endpoint_url(gateway_url, "/v1/models"),
            token=gateway_token,
            payload=None,
            timeout_seconds=config.gateway_timeout_seconds,
        )
        print(
            f"/v1/models status={models_status} timing={models_ended - models_started:.2f}s "
            f"{summarize_gateway_models(models_response)}"
        )

        chat_response, chat_status, chat_started, chat_ended = perform_gateway_request(
            url=build_gateway_endpoint_url(gateway_url, "/v1/chat/completions"),
            token=gateway_token,
            payload=build_gateway_chat_payload(gateway_agent, "Say only: ready."),
            timeout_seconds=config.gateway_timeout_seconds,
        )
        print(
            f"/v1/chat/completions status={chat_status} timing={chat_ended - chat_started:.2f}s"
        )
        print(f"reply={extract_gateway_reply_text(chat_response)}")
    except OpenClawError as exc:
        print(f"Gateway probe failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
