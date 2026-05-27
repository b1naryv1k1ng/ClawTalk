from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_PATH = Path("clawtalk.toml")
EXAMPLE_CONFIG_PATH = Path("clawtalk.example.toml")


@dataclass
class AppConfig:
    ssh_target: str = ""
    ssh_host: str = "eitri"
    ssh_user: str = "openclaw"
    openclaw_agent: str = "main"
    openclaw_command_template: str = (
        "openclaw agent --agent {agent} --message {message}"
    )
    mute_tts: bool = False
    push_to_talk_hotkey: str = "ctrl+shift+f9"
    recordings_directory: str = ""
    input_device_index: Optional[int] = None
    stt_backend: str = "faster_whisper"
    whisper_model_size: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    auto_transcribe_after_recording: bool = False
    auto_send_after_transcription: bool = False


class ConfigError(Exception):
    pass


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}. "
            f"Copy {EXAMPLE_CONFIG_PATH} to {config_path} and update it if needed."
        )

    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except OSError as exc:
        raise ConfigError(f"Could not read config file: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in config file: {exc}") from exc

    return AppConfig(
        ssh_target=_read_string(raw_config, "ssh_target", AppConfig.ssh_target),
        ssh_host=_read_string(raw_config, "ssh_host", AppConfig.ssh_host),
        ssh_user=_read_string(raw_config, "ssh_user", AppConfig.ssh_user),
        openclaw_agent=_read_string(
            raw_config, "openclaw_agent", AppConfig.openclaw_agent
        ),
        openclaw_command_template=_read_string(
            raw_config,
            "openclaw_command_template",
            AppConfig.openclaw_command_template,
        ),
        mute_tts=_read_bool(raw_config, "mute_tts", AppConfig.mute_tts),
        push_to_talk_hotkey=_read_string(
            raw_config, "push_to_talk_hotkey", AppConfig.push_to_talk_hotkey
        ),
        recordings_directory=_read_string(
            raw_config, "recordings_directory", AppConfig.recordings_directory
        ),
        input_device_index=_read_optional_int(
            raw_config, "input_device_index", AppConfig.input_device_index
        ),
        stt_backend=_read_string(raw_config, "stt_backend", AppConfig.stt_backend),
        whisper_model_size=_read_string(
            raw_config, "whisper_model_size", AppConfig.whisper_model_size
        ),
        whisper_device=_read_string(
            raw_config, "whisper_device", AppConfig.whisper_device
        ),
        whisper_compute_type=_read_string(
            raw_config, "whisper_compute_type", AppConfig.whisper_compute_type
        ),
        auto_transcribe_after_recording=_read_bool(
            raw_config,
            "auto_transcribe_after_recording",
            AppConfig.auto_transcribe_after_recording,
        ),
        auto_send_after_transcription=_read_bool(
            raw_config,
            "auto_send_after_transcription",
            AppConfig.auto_send_after_transcription,
        ),
    )


def _read_string(config: Dict[str, Any], key: str, default: str) -> str:
    value = config.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"Config value '{key}' must be a string.")
    return value


def _read_bool(config: Dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"Config value '{key}' must be true or false.")
    return value


def _read_optional_int(config: Dict[str, Any], key: str, default: Optional[int]) -> Optional[int]:
    value = config.get(key, default)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ConfigError(f"Config value '{key}' must be an integer or omitted.")
    return value
