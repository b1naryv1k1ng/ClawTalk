from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class OpenClawError(Exception):
    pass


@dataclass
class OpenClawResponse:
    reply_text: str
    transport_name: str
    started_at: float
    ended_at: float
    duration_seconds: float
    return_code: int
    output_length: int
    error_length: int

    @property
    def ssh_started_at(self) -> float:
        return self.started_at

    @property
    def ssh_ended_at(self) -> float:
        return self.ended_at

    @property
    def ssh_duration_seconds(self) -> float:
        return self.duration_seconds

    @property
    def stdout_length(self) -> int:
        return self.output_length

    @property
    def stderr_length(self) -> int:
        return self.error_length


class OpenClawClient(ABC):
    def send_message(self, message: str) -> str:
        return self.send_message_details(message).reply_text

    @abstractmethod
    def send_message_details(self, message: str) -> OpenClawResponse:
        raise NotImplementedError
