from abc import ABC, abstractmethod


class OpenClawClient(ABC):
    @abstractmethod
    def send_message(self, message: str) -> str:
        raise NotImplementedError
