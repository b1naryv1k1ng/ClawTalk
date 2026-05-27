from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional


class TTSError(Exception):
    pass


class TTSBackend(ABC):
    @property
    @abstractmethod
    def backend_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def set_error_handler(self, handler: Callable[[str], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_completion_handler(self, handler: Callable[[], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def speak_async(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        raise NotImplementedError
