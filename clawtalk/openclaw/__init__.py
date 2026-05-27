from clawtalk.config import AppConfig
from clawtalk.openclaw.base import OpenClawClient, OpenClawError, OpenClawResponse
from clawtalk.openclaw.gateway_client import OpenClawGatewayClient
from clawtalk.openclaw.ssh_client import OpenClawSSHClient


def create_openclaw_client(config: AppConfig) -> OpenClawClient:
    transport = config.transport.strip().lower() or "ssh"
    if transport == "ssh":
        return OpenClawSSHClient(config)
    if transport == "gateway":
        return OpenClawGatewayClient(config)
    raise OpenClawError(
        f"Unsupported transport '{config.transport}'. Expected 'ssh' or 'gateway'."
    )


__all__ = [
    "OpenClawClient",
    "OpenClawResponse",
    "OpenClawSSHClient",
    "OpenClawGatewayClient",
    "OpenClawError",
    "create_openclaw_client",
]
