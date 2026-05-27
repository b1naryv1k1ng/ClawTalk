from __future__ import annotations

import audioop
import logging
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2
SILENCE_PEAK_THRESHOLD = 10
SILENCE_RMS_THRESHOLD = 5


class RecorderError(Exception):
    pass


@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_sample_rate: float
    is_default_input: bool


@dataclass
class RecordingSession:
    device_index: int
    device_name: str
    started_at: float
    sample_rate: int
    channels: int


@dataclass
class RecordingStats:
    peak_amplitude: int
    rms_level: int
    appears_silent: bool


@dataclass
class RecordingResult:
    file_path: Path
    duration_seconds: float
    file_size_bytes: int
    device_index: int
    device_name: str
    stats: RecordingStats


class AudioRecorder:
    def __init__(
        self,
        recordings_directory: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        input_device_index: Optional[int] = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._input_device_index = input_device_index
        self._recordings_directory = Path(
            recordings_directory or Path(tempfile.gettempdir()) / "clawtalk-recordings"
        )
        self._stream = None
        self._frames: List[bytes] = []
        self._lock = threading.Lock()
        self._session: Optional[RecordingSession] = None

    @property
    def input_device_index(self) -> Optional[int]:
        return self._input_device_index

    def is_recording(self) -> bool:
        with self._lock:
            return self._session is not None

    def get_available_input_devices(self) -> List[AudioDeviceInfo]:
        sd = self._get_sounddevice_module()
        try:
            devices = sd.query_devices()
            default_input = sd.default.device[0]
        except Exception as exc:
            raise RecorderError(f"Could not query audio devices: {exc}") from exc

        input_devices: List[AudioDeviceInfo] = []
        for index, device in enumerate(devices):
            max_input_channels = int(device.get("max_input_channels", 0))
            if max_input_channels <= 0:
                continue
            input_devices.append(
                AudioDeviceInfo(
                    index=index,
                    name=str(device.get("name", f"Device {index}")),
                    max_input_channels=max_input_channels,
                    default_sample_rate=float(device.get("default_samplerate", 0.0)),
                    is_default_input=index == default_input,
                )
            )

        return input_devices

    def get_selected_input_device(self) -> AudioDeviceInfo:
        devices = self.get_available_input_devices()
        if not devices:
            raise RecorderError("No input devices with microphone channels were found.")

        if self._input_device_index is None:
            for device in devices:
                if device.is_default_input:
                    return device
            raise RecorderError("No default microphone is configured on this system.")

        for device in devices:
            if device.index == self._input_device_index:
                return device

        raise RecorderError(
            f"Input device index {self._input_device_index} was not found or has no input channels."
        )

    def get_default_input_device_name(self) -> str:
        return self.get_selected_input_device().name

    def start_recording(self) -> RecordingSession:
        with self._lock:
            if self._session is not None:
                raise RecorderError("Recording is already in progress.")

            selected_device = self.get_selected_input_device()
            sample_rate = self._resolve_input_sample_rate(selected_device)
            sd = self._get_sounddevice_module()
            self._frames = []

            def callback(indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
                if status:
                    logger.warning("Recorder status: %s", status)
                chunk = bytes(indata)
                if chunk:
                    self._frames.append(chunk)
                    try:
                        peak = audioop.max(chunk, DEFAULT_SAMPLE_WIDTH)
                        rms = audioop.rms(chunk, DEFAULT_SAMPLE_WIDTH)
                    except audioop.error:
                        peak = 0
                        rms = 0
                    if peak > 0 or rms > 0:
                        logger.debug(
                            "Recorder callback received audio. bytes=%s peak=%s rms=%s",
                            len(chunk),
                            peak,
                            rms,
                        )

            try:
                self._stream = sd.RawInputStream(
                    samplerate=sample_rate,
                    channels=self._channels,
                    dtype="int16",
                    device=selected_device.index,
                    callback=callback,
                )
                self._stream.start()
            except Exception as exc:
                self._stream = None
                self._frames = []
                raise RecorderError(f"Could not start microphone recording: {exc}") from exc

            self._session = RecordingSession(
                device_index=selected_device.index,
                device_name=selected_device.name,
                started_at=time.time(),
                sample_rate=sample_rate,
                channels=self._channels,
            )
            logger.info(
                "Recording started. device_index=%s device_name=%s sample_rate=%s channels=%s",
                selected_device.index,
                selected_device.name,
                sample_rate,
                self._channels,
            )
            return self._session

    def stop_recording(self) -> RecordingResult:
        with self._lock:
            if self._session is None:
                raise RecorderError("Recording is not in progress.")

            stream = self._stream
            session = self._session
            frames = list(self._frames)
            self._stream = None
            self._session = None
            self._frames = []

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                raise RecorderError(f"Could not stop microphone recording: {exc}") from exc

        if not frames:
            raise RecorderError("Recording captured no frames. Check the selected microphone.")

        audio_bytes = b"".join(frames)
        if not audio_bytes:
            raise RecorderError("Recording captured an empty audio buffer.")

        duration_seconds = max(time.time() - session.started_at, 0.0)
        if duration_seconds <= 0:
            raise RecorderError("Recording duration was too short to save.")

        self._recordings_directory.mkdir(parents=True, exist_ok=True)
        file_path = build_recording_file_path(
            self._recordings_directory, session.started_at
        )

        try:
            with wave.open(str(file_path), "wb") as wav_file:
                wav_file.setnchannels(session.channels)
                wav_file.setsampwidth(DEFAULT_SAMPLE_WIDTH)
                wav_file.setframerate(session.sample_rate)
                wav_file.writeframes(audio_bytes)
        except OSError as exc:
            raise RecorderError(f"Could not write WAV file: {exc}") from exc

        file_size_bytes = file_path.stat().st_size
        if file_size_bytes <= 44:
            raise RecorderError("Recording was empty after saving.")

        stats = analyze_audio_levels(audio_bytes)
        logger.info(
            "Recording saved. path=%s duration=%.2fs size=%s peak=%s rms=%s silent=%s",
            file_path,
            duration_seconds,
            file_size_bytes,
            stats.peak_amplitude,
            stats.rms_level,
            stats.appears_silent,
        )
        if stats.appears_silent:
            logger.warning(
                "Recording appears silent. device_index=%s device_name=%s peak=%s rms=%s",
                session.device_index,
                session.device_name,
                stats.peak_amplitude,
                stats.rms_level,
            )

        return RecordingResult(
            file_path=file_path,
            duration_seconds=duration_seconds,
            file_size_bytes=file_size_bytes,
            device_index=session.device_index,
            device_name=session.device_name,
            stats=stats,
        )

    def _resolve_input_sample_rate(self, device: AudioDeviceInfo) -> int:
        if device.max_input_channels <= 0:
            raise RecorderError(
                f"Selected device {device.index} does not have input channels."
            )

        sd = self._get_sounddevice_module()
        requested_rate = int(self._sample_rate)
        fallback_rate = int(device.default_sample_rate) if device.default_sample_rate > 0 else 0

        try:
            self._check_input_settings(sd, device.index, requested_rate)
            return requested_rate
        except Exception as requested_exc:
            if fallback_rate and fallback_rate != requested_rate:
                logger.warning(
                    "Requested sample rate not supported. device_index=%s requested_rate=%s fallback_rate=%s error=%s",
                    device.index,
                    requested_rate,
                    fallback_rate,
                    requested_exc,
                )
                try:
                    self._check_input_settings(sd, device.index, fallback_rate)
                    logger.info(
                        "Using fallback sample rate for device. device_index=%s sample_rate=%s",
                        device.index,
                        fallback_rate,
                    )
                    return fallback_rate
                except Exception as fallback_exc:
                    raise RecorderError(
                        "Input device "
                        f"{device.index} does not accept requested sample rate {requested_rate} Hz "
                        f"or fallback sample rate {fallback_rate} Hz: "
                        f"requested_error={requested_exc}; fallback_error={fallback_exc}"
                    ) from fallback_exc

            raise RecorderError(
                f"Input device {device.index} does not accept {requested_rate} Hz mono capture: {requested_exc}"
            ) from requested_exc

    def _check_input_settings(self, sounddevice_module, device_index: int, sample_rate: int) -> None:
        sounddevice_module.check_input_settings(
            device=device_index,
            channels=self._channels,
            dtype="int16",
            samplerate=sample_rate,
        )

    def _get_sounddevice_module(self):
        return _load_sounddevice()


def _load_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RecorderError(
            "The 'sounddevice' package is not installed. Run pip install -r requirements.txt."
        ) from exc
    return sd


def analyze_audio_levels(audio_bytes: bytes) -> RecordingStats:
    if not audio_bytes:
        return RecordingStats(peak_amplitude=0, rms_level=0, appears_silent=True)

    try:
        peak = audioop.max(audio_bytes, DEFAULT_SAMPLE_WIDTH)
        rms = audioop.rms(audio_bytes, DEFAULT_SAMPLE_WIDTH)
    except audioop.error:
        peak = 0
        rms = 0
    appears_silent = peak <= SILENCE_PEAK_THRESHOLD and rms <= SILENCE_RMS_THRESHOLD
    return RecordingStats(peak_amplitude=peak, rms_level=rms, appears_silent=appears_silent)


def format_recording_result(result: RecordingResult) -> str:
    silent_suffix = " | WARNING: recording appears silent" if result.stats.appears_silent else ""
    return (
        f"Saved recording: {result.file_path} | "
        f"duration={result.duration_seconds:.2f}s | "
        f"size={format_file_size(result.file_size_bytes)} | "
        f"input={result.device_name} (index {result.device_index}) | "
        f"peak={result.stats.peak_amplitude} | "
        f"rms={result.stats.rms_level}"
        f"{silent_suffix}"
    )


def format_audio_device(device: AudioDeviceInfo) -> str:
    default_tag = " [default]" if device.is_default_input else ""
    return (
        f"[{device.index}] {device.name}{default_tag} | "
        f"input_channels={device.max_input_channels} | "
        f"default_sample_rate={device.default_sample_rate:.0f}"
    )


def format_file_size(file_size_bytes: int) -> str:
    if file_size_bytes < 1024:
        return f"{file_size_bytes} B"
    if file_size_bytes < 1024 * 1024:
        return f"{file_size_bytes / 1024:.1f} KB"
    return f"{file_size_bytes / (1024 * 1024):.1f} MB"


def build_recording_file_path(recordings_directory: Path, started_at: float) -> Path:
    timestamp = datetime.fromtimestamp(started_at).strftime("%Y%m%d-%H%M%S-%f")
    return recordings_directory / f"clawtalk-recording-{timestamp}-{uuid.uuid4().hex[:8]}.wav"
