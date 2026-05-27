from __future__ import annotations

import logging
import shlex
import subprocess
import time
from typing import Optional

from clawtalk.config import AppConfig
from clawtalk.openclaw.base import OpenClawClient, OpenClawError, OpenClawResponse


logger = logging.getLogger(__name__)


class OpenClawSSHClient(OpenClawClient):
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def send_message_details(self, message: str) -> OpenClawResponse:
        sanitized_message = message.strip()
        if not sanitized_message:
            raise OpenClawError("Message is empty.")

        remote_command = build_openclaw_remote_command(
            self._config.openclaw_command_template,
            self._config.openclaw_agent,
            sanitized_message,
        )
        ssh_target = resolve_ssh_target(
            ssh_target=self._config.ssh_target,
            ssh_user=self._config.ssh_user,
            ssh_host=self._config.ssh_host,
        )

        started_at = time.perf_counter()
        try:
            completed = subprocess.run(
                ["ssh", ssh_target, remote_command],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise OpenClawError(
                "The 'ssh' command was not found. Install OpenSSH Client on Windows."
            ) from exc
        except OSError as exc:
            raise OpenClawError(f"Could not run SSH command: {exc}") from exc
        ended_at = time.perf_counter()

        stdout = normalize_ssh_output(completed.stdout)
        stderr = normalize_ssh_output(completed.stderr)
        logger.info(
            "SSH timing. start=%.6f end=%.6f duration=%.3fs returncode=%s stdout_length=%s stderr_length=%s",
            started_at,
            ended_at,
            ended_at - started_at,
            completed.returncode,
            len(stdout),
            len(stderr),
        )

        if completed.returncode != 0:
            details = stderr or stdout or f"SSH exited with code {completed.returncode}."
            raise OpenClawError(details)

        if not stdout:
            raise OpenClawError("OpenClaw returned an empty response.")

        return OpenClawResponse(
            reply_text=stdout,
            transport_name="ssh",
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=ended_at - started_at,
            return_code=completed.returncode,
            output_length=len(stdout),
            error_length=len(stderr),
        )


def build_openclaw_remote_command(
    command_template: str, agent: str, message: str
) -> str:
    return command_template.format(
        agent=shlex.quote(agent),
        message=shlex.quote(message),
    )


def resolve_ssh_target(
    ssh_target: str, ssh_user: Optional[str], ssh_host: Optional[str]
) -> str:
    if ssh_target.strip():
        return ssh_target.strip()

    user = (ssh_user or "").strip()
    host = (ssh_host or "").strip()
    if user and host:
        return f"{user}@{host}"
    if host:
        return host

    raise OpenClawError(
        "SSH target is not configured. Set ssh_target or ssh_host in clawtalk.toml."
    )


def normalize_ssh_output(value: str) -> str:
    return value.strip()
