import logging
from pathlib import Path


def configure_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(Path("clawtalk.log"), encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
