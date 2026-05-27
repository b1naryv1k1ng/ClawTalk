from __future__ import annotations

import shlex
import subprocess
from typing import Optional

from clawtalk.config import AppConfig
from clawtalk.openclaw.base import OpenClawClient


class OpenClawError(Exception):
    pass


class OpenClawSSHClient(OpenClawClient):
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def send_message(self, message: str) -> str:
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

        try:
            completed = subprocess.run(
                ["ssh", ssh_target, remote_command],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise OpenClawError(
                "The 'ssh' command was not found. Install OpenSSH Client on Windows."
            ) from exc
        except OSError as exc:
            raise OpenClawError(f"Could not run SSH command: {exc}") from exc

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

        if completed.returncode != 0:
            details = stderr or stdout or f"SSH exited with code {completed.returncode}."
            raise OpenClawError(details)

        if not stdout:
            raise OpenClawError("OpenClaw returned an empty response.")

        return stdout


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
