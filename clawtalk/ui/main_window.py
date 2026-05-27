from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any, Optional, Tuple

from clawtalk.config import AppConfig, ConfigError, load_config
from clawtalk.hotkey import GlobalHotkeyManager, HotkeyError
from clawtalk.logging_setup import configure_logging
from clawtalk.openclaw import OpenClawError, OpenClawSSHClient
from clawtalk.openclaw.ssh_client import resolve_ssh_target
from clawtalk.recorder import (
    AudioRecorder,
    RecorderError,
    RecordingResult,
    format_audio_device,
    format_recording_result,
)
from clawtalk.stt import STTError, STTResult, create_stt_backend
from clawtalk.tts import WindowsTTS


UIEvent = Tuple[str, Any, Any]
logger = logging.getLogger(__name__)


class MainWindow:
    def __init__(self) -> None:
        configure_logging()
        self.root = tk.Tk()
        self.root.title("ClawTalk")
        self.root.geometry("980x800")
        self.root.minsize(820, 640)

        self._events: "queue.Queue[UIEvent]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._config: Optional[AppConfig] = None
        self._client: Optional[OpenClawSSHClient] = None
        self._recorder: Optional[AudioRecorder] = None
        self._stt_backend = None
        self._hotkey_manager: Optional[GlobalHotkeyManager] = None
        self._tts = WindowsTTS()
        self._tts.set_error_handler(self._post_tts_error)
        self._tts.set_completion_handler(self._post_tts_complete)
        self._recording_mode = "idle"
        self._pending_stop_request = False
        self._transcription_mode = "idle"
        self._last_recording_result: Optional[RecordingResult] = None

        self.connection_var = tk.StringVar(value="Loading")
        self.state_var = tk.StringVar(value="Starting")
        self.mute_tts_var = tk.BooleanVar(value=False)
        self.tts_indicator_var = tk.StringVar(value="TTS: Unknown")
        self.recording_indicator_var = tk.StringVar(value="Mic: Loading")

        self._build_layout()
        self.mute_tts_var.trace_add("write", self._on_mute_changed)
        self._load_dependencies()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_events)

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)

        ttk.Label(container, text="ClawTalk", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        status_frame = ttk.LabelFrame(container, text="Status", padding=10)
        status_frame.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(3, weight=1)

        ttk.Label(status_frame, text="Connection:").grid(
            row=0, column=0, sticky="nw", padx=(0, 8)
        )
        ttk.Label(status_frame, textvariable=self.connection_var).grid(
            row=0, column=1, sticky="nw"
        )
        ttk.Label(status_frame, text="State:").grid(
            row=0, column=2, sticky="nw", padx=(16, 8)
        )
        ttk.Label(status_frame, textvariable=self.state_var).grid(
            row=0, column=3, sticky="nw"
        )
        ttk.Label(status_frame, textvariable=self.tts_indicator_var).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        ttk.Label(status_frame, textvariable=self.recording_indicator_var).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )

        input_frame = ttk.LabelFrame(container, text="Message", padding=10)
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)

        self.message_input = tk.Text(input_frame, height=5, wrap="word")
        self.message_input.grid(row=0, column=0, sticky="ew")
        self.message_input.bind("<Control-Return>", self._on_ctrl_enter)

        actions = ttk.Frame(input_frame)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        actions.columnconfigure(4, weight=1)

        self.mute_checkbox = ttk.Checkbutton(
            actions, text="Mute TTS", variable=self.mute_tts_var
        )
        self.mute_checkbox.grid(row=0, column=0, sticky="w")

        ttk.Label(actions, text="Ctrl+Enter sends").grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )

        self.record_button = ttk.Button(
            actions, text="Start Recording", command=self._toggle_recording
        )
        self.record_button.grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.transcribe_button = ttk.Button(
            actions,
            text="Transcribe Last Recording",
            command=self._transcribe_last_recording,
            state=tk.DISABLED,
        )
        self.transcribe_button.grid(row=0, column=3, sticky="w", padx=(12, 0))

        self.send_button = ttk.Button(actions, text="Send", command=self._send_message)
        self.send_button.grid(row=0, column=5, sticky="e")

        transcript_frame = ttk.LabelFrame(container, text="Last User Message", padding=10)
        transcript_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        transcript_frame.columnconfigure(0, weight=1)

        self.user_message_display = tk.Text(
            transcript_frame, height=5, wrap="word", state=tk.DISABLED
        )
        self.user_message_display.grid(row=0, column=0, sticky="nsew")

        reply_frame = ttk.LabelFrame(container, text="Last OpenClaw Reply", padding=10)
        reply_frame.grid(row=4, column=0, sticky="nsew", pady=(12, 0))
        reply_frame.columnconfigure(0, weight=1)

        self.reply_display = tk.Text(reply_frame, height=7, wrap="word", state=tk.DISABLED)
        self.reply_display.grid(row=0, column=0, sticky="nsew")

        conversation_frame = ttk.LabelFrame(
            container, text="Conversation Log", padding=10
        )
        conversation_frame.grid(row=5, column=0, sticky="nsew", pady=(12, 0))
        conversation_frame.columnconfigure(0, weight=1)
        conversation_frame.rowconfigure(1, weight=1)

        log_actions = ttk.Frame(conversation_frame)
        log_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        log_actions.columnconfigure(0, weight=1)

        ttk.Button(log_actions, text="Clear Log", command=self._clear_log).grid(
            row=0, column=1, sticky="e"
        )

        self.conversation_log = tk.Text(
            conversation_frame, wrap="word", state=tk.DISABLED
        )
        self.conversation_log.grid(row=1, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            conversation_frame, orient=tk.VERTICAL, command=self.conversation_log.yview
        )
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.conversation_log.configure(yscrollcommand=scrollbar.set)

        ttk.Label(
            container,
            text="Edit clawtalk.toml in the repo root to change SSH, hotkey, recording, and transcription settings.",
        ).grid(row=6, column=0, sticky="w", pady=(12, 0))

    def _load_dependencies(self) -> None:
        try:
            self._config = load_config()
            self._client = OpenClawSSHClient(self._config)
            self._recorder = AudioRecorder(
                recordings_directory=self._config.recordings_directory or None,
                input_device_index=self._config.input_device_index,
            )
            self._stt_backend = create_stt_backend(self._config)
        except (ConfigError, STTError) as exc:
            self.connection_var.set("Config error")
            self._set_state("Error")
            self._append_log("SYSTEM", str(exc))
            self._show_text(self.reply_display, str(exc))
            return

        self.mute_tts_var.set(self._config.mute_tts)
        ssh_target = resolve_ssh_target(
            ssh_target=self._config.ssh_target,
            ssh_user=self._config.ssh_user,
            ssh_host=self._config.ssh_host,
        )
        self.connection_var.set(f"{ssh_target} (agent: {self._config.openclaw_agent})")
        self._set_state("Idle")

        self._append_log("SYSTEM", "Configuration loaded. Ready to send messages.")
        self._append_log(
            "SYSTEM",
            f"STT backend: {self._config.stt_backend} (model: {self._config.whisper_model_size})",
        )
        self._initialize_recording_status()
        self._initialize_hotkey()

    def _initialize_recording_status(self) -> None:
        if self._recorder is None or self._config is None:
            self.recording_indicator_var.set("Mic: Recorder unavailable")
            return

        try:
            devices = self._recorder.get_available_input_devices()
            for device in devices:
                logger.info("Audio input device: %s", format_audio_device(device))
            selected_device = self._recorder.get_selected_input_device()
            self.recording_indicator_var.set(
                f"Mic: [{selected_device.index}] {selected_device.name} | PTT: {self._config.push_to_talk_hotkey}"
            )
            self._append_log(
                "SYSTEM",
                f"Selected input device: [{selected_device.index}] {selected_device.name}",
            )
        except RecorderError as exc:
            self.recording_indicator_var.set(
                f"Mic: Error | PTT: {self._config.push_to_talk_hotkey}"
            )
            self._append_log("RECORDER ERROR", str(exc))
            self._show_text(self.reply_display, str(exc))

    def _initialize_hotkey(self) -> None:
        if self._config is None:
            return
        try:
            self._hotkey_manager = GlobalHotkeyManager(
                hotkey=self._config.push_to_talk_hotkey,
                on_press_start=self._queue_hotkey_start,
                on_release_stop=self._queue_hotkey_stop,
                on_error=self._post_hotkey_error,
            )
            self._hotkey_manager.start()
            self._append_log(
                "SYSTEM", f"Global push-to-talk ready: {self._hotkey_manager.hotkey_label}"
            )
        except HotkeyError as exc:
            self._append_log("HOTKEY ERROR", str(exc))
            self._show_text(self.reply_display, str(exc))

    def _on_ctrl_enter(self, event: tk.Event) -> str:
        self._send_message()
        return "break"

    def _send_message(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        if self._recording_mode in {"starting", "recording", "processing"}:
            self._append_log("SYSTEM", "Finish the current recording before sending.")
            return
        if self._transcription_mode == "transcribing":
            self._append_log("SYSTEM", "Wait for the current transcription to finish.")
            return

        if self._client is None:
            self._append_log("SYSTEM", "Cannot send message until config loads successfully.")
            self._set_state("Error")
            return

        message = self.message_input.get("1.0", tk.END).strip()
        if not message:
            self._set_state("Error")
            self._append_log("SYSTEM", "Please enter a message before sending.")
            return

        self._show_text(self.user_message_display, message)
        self._append_log("YOU", message)
        self._set_state("Sending")

        self._worker = threading.Thread(
            target=self._send_message_worker, args=(message,), daemon=True
        )
        self._worker.start()

    def _send_message_worker(self, message: str) -> None:
        try:
            assert self._client is not None
            reply = self._client.send_message(message)
        except OpenClawError as exc:
            self._events.put(("error", str(exc), ""))
            return
        except Exception as exc:  # pragma: no cover
            self._events.put(("error", f"Unexpected error: {exc}", ""))
            return

        self._events.put(("reply", message, reply))

    def _toggle_recording(self) -> None:
        if self._recording_mode in {"starting", "recording"}:
            self._request_stop_recording("button")
        else:
            self._request_start_recording("button")

    def _queue_hotkey_start(self) -> None:
        self._events.put(("record_request_start", "hotkey", ""))

    def _queue_hotkey_stop(self) -> None:
        self._events.put(("record_request_stop", "hotkey", ""))

    def _request_start_recording(self, source: str) -> None:
        logger.info(
            "Recording start requested. source=%s mode=%s recorder_busy=%s input_device_index=%s",
            source,
            self._recording_mode,
            self._recorder.is_recording() if self._recorder is not None else None,
            self._recorder.input_device_index if self._recorder is not None else None,
        )
        if self._worker is not None and self._worker.is_alive():
            self._append_log("SYSTEM", "Cannot start recording while a send is in progress.")
            return
        if self._transcription_mode == "transcribing":
            self._append_log("SYSTEM", "Cannot start recording while transcription is in progress.")
            return
        if self._recording_mode in {"starting", "recording", "processing"}:
            logger.info(
                "Recording start ignored because recorder mode is busy. source=%s mode=%s",
                source,
                self._recording_mode,
            )
            return
        if self._recorder is None:
            self._append_log("RECORDER ERROR", "Recorder is not available.")
            self._set_state("Error")
            return
        if self._recorder.is_recording():
            logger.warning(
                "Recorder reported an active session before start. source=%s mode=%s",
                source,
                self._recording_mode,
            )
            self._recording_mode = "recording"
            self._set_state("Recording")
            return

        self._recording_mode = "starting"
        self._pending_stop_request = False
        self._set_state("Recording")

        threading.Thread(
            target=self._start_recording_worker, args=(source,), daemon=True
        ).start()

    def _start_recording_worker(self, source: str) -> None:
        try:
            assert self._recorder is not None
            logger.info(
                "Starting recorder worker. source=%s input_device_index=%s",
                source,
                self._recorder.input_device_index,
            )
            session = self._recorder.start_recording()
        except RecorderError as exc:
            logger.exception("Recorder start failed. source=%s", source)
            self._events.put(("recording_error", source, f"start|{exc}"))
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected recorder start failure. source=%s", source)
            self._events.put(
                ("recording_error", source, f"start|Unexpected recorder error: {exc}")
            )
            return

        self._events.put(("recording_started", source, session.device_name))

    def _request_stop_recording(self, source: str) -> None:
        if self._recording_mode == "starting":
            self._pending_stop_request = True
            return
        if self._recording_mode != "recording":
            return

        self._recording_mode = "processing"
        self._set_state("Processing")
        threading.Thread(
            target=self._stop_recording_worker, args=(source,), daemon=True
        ).start()

    def _stop_recording_worker(self, source: str) -> None:
        try:
            assert self._recorder is not None
            logger.info("Stopping recorder worker. source=%s", source)
            result = self._recorder.stop_recording()
        except RecorderError as exc:
            logger.exception("Recorder stop failed. source=%s", source)
            self._events.put(("recording_error", source, f"stop|{exc}"))
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected recorder stop failure. source=%s", source)
            self._events.put(
                ("recording_error", source, f"stop|Unexpected recorder error: {exc}")
            )
            return

        self._events.put(("recording_saved", source, result))

    def _transcribe_last_recording(self) -> None:
        if self._transcription_mode == "transcribing":
            return
        if self._last_recording_result is None:
            self._append_log("SYSTEM", "Record audio before transcribing.")
            return
        if not self._last_recording_result.file_path.exists():
            self._handle_error(f"Recording file not found: {self._last_recording_result.file_path}")
            return
        if self._stt_backend is None:
            self._handle_error("Speech-to-text backend is not configured.")
            return

        self._transcription_mode = "transcribing"
        self._set_state("Transcribing")
        threading.Thread(target=self._transcribe_last_recording_worker, daemon=True).start()

    def _transcribe_last_recording_worker(self) -> None:
        try:
            assert self._last_recording_result is not None
            assert self._stt_backend is not None
            logger.info(
                "Starting transcription worker. path=%s backend=%s",
                self._last_recording_result.file_path,
                self._config.stt_backend if self._config is not None else "unknown",
            )
            result = self._stt_backend.transcribe(str(self._last_recording_result.file_path))
        except STTError as exc:
            logger.exception("Transcription failed.")
            self._events.put(("transcription_error", str(exc), ""))
            return
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected transcription failure.")
            self._events.put(("transcription_error", f"Unexpected transcription error: {exc}", ""))
            return

        self._events.put(("transcription_complete", result, ""))

    def _drain_events(self) -> None:
        while True:
            try:
                event_type, first, second = self._events.get_nowait()
            except queue.Empty:
                break

            if event_type == "reply":
                self._handle_reply(first, second)
            elif event_type == "error":
                self._handle_error(first)
            elif event_type == "tts_error":
                self._append_log("TTS ERROR", first)
                self._show_text(self.reply_display, first)
                self._set_state("Error")
            elif event_type == "tts_complete" and self.state_var.get() == "Speaking":
                self._set_state("Idle")
            elif event_type == "record_request_start":
                self._request_start_recording(first)
            elif event_type == "record_request_stop":
                self._request_stop_recording(first)
            elif event_type == "recording_started":
                self._handle_recording_started(first, second)
            elif event_type == "recording_saved":
                self._handle_recording_saved(first, second)
            elif event_type == "recording_error":
                self._handle_recording_error(first, second)
            elif event_type == "hotkey_error":
                self._append_log("HOTKEY ERROR", first)
                self._show_text(self.reply_display, first)
            elif event_type == "transcription_complete":
                self._handle_transcription_complete(first)
            elif event_type == "transcription_error":
                self._handle_transcription_error(first)

        self.root.after(100, self._drain_events)

    def _handle_reply(self, message: str, reply: str) -> None:
        self._show_text(self.reply_display, reply)
        self._append_log("OPENCLAW", reply)
        self.message_input.delete("1.0", tk.END)

        if not self.mute_tts_var.get():
            self._set_state("Speaking")
            logger.info("TTS request queued from UI. text_length=%s", len(reply))
            self._tts.speak_async(reply)
        else:
            logger.info("TTS muted/skipped for reply. text_length=%s", len(reply))
            self._set_state("Idle")

    def _handle_error(self, error_message: str) -> None:
        self._show_text(self.reply_display, error_message)
        self._append_log("ERROR", error_message)
        self._set_state("Error")

    def _handle_recording_started(self, source: str, device_name: str) -> None:
        self._recording_mode = "recording"
        if self._config is not None:
            self.recording_indicator_var.set(
                f"Mic: {device_name} | PTT: {self._config.push_to_talk_hotkey}"
            )
        self._append_log("RECORDER", f"Recording started via {source}. input={device_name}")
        self._refresh_controls()
        if self._pending_stop_request:
            self._pending_stop_request = False
            self._request_stop_recording(source)

    def _handle_recording_saved(self, source: str, result: RecordingResult) -> None:
        self._recording_mode = "idle"
        self._last_recording_result = result
        self._set_state("Idle")
        self._append_log("RECORDER", f"Recording stopped via {source}.")
        self._append_log("RECORDER", format_recording_result(result))
        if result.stats.appears_silent:
            self._show_text(
                self.reply_display,
                "Recording saved, but it appears silent. Check the selected input device.",
            )
        if self._config is not None and self._config.auto_transcribe_after_recording:
            self._transcribe_last_recording()

    def _handle_recording_error(self, source: str, error_message: str) -> None:
        self._recording_mode = "idle"
        self._pending_stop_request = False
        stage, _, clean_message = error_message.partition("|")
        if source == "hotkey" and self._hotkey_manager is not None:
            if stage == "start":
                self._hotkey_manager.notify_recording_start_failed()
            else:
                self._hotkey_manager.notify_recording_stop_failed()
        display_message = clean_message or error_message
        logger.error(
            "Recording error handled in UI. source=%s stage=%s message=%s",
            source,
            stage or "unknown",
            display_message,
        )
        self.recording_indicator_var.set(f"Mic: Error | {display_message}")
        self._show_text(self.reply_display, display_message)
        self._append_log("RECORDER ERROR", f"{source}: {display_message}")
        self._set_state("Error")

    def _handle_transcription_complete(self, result: STTResult) -> None:
        self._transcription_mode = "idle"
        if result.transcript_text:
            self._set_message_input(result.transcript_text)
        else:
            self._show_text(
                self.reply_display,
                "Transcription completed, but no speech was detected.",
            )

        self._append_log(
            "STT",
            format_transcription_summary(result),
        )
        if result.diagnostics:
            self._append_log("STT", " | ".join(result.diagnostics))
        self._set_state("Idle")

    def _handle_transcription_error(self, error_message: str) -> None:
        self._transcription_mode = "idle"
        self._show_text(self.reply_display, error_message)
        self._append_log("STT ERROR", error_message)
        self._set_state("Error")

    def _post_tts_error(self, message: str) -> None:
        self._events.put(("tts_error", message, ""))

    def _post_tts_complete(self) -> None:
        self._events.put(("tts_complete", "", ""))

    def _post_hotkey_error(self, message: str) -> None:
        self._events.put(("hotkey_error", message, ""))

    def _show_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)

    def _set_message_input(self, value: str) -> None:
        self.message_input.delete("1.0", tk.END)
        self.message_input.insert("1.0", value)

    def _clear_log(self) -> None:
        self.conversation_log.configure(state=tk.NORMAL)
        self.conversation_log.delete("1.0", tk.END)
        self.conversation_log.configure(state=tk.DISABLED)
        self._append_log("SYSTEM", "Conversation log cleared.")

    def _on_mute_changed(self, *_args: object) -> None:
        self._update_tts_indicator()

    def _update_tts_indicator(self) -> None:
        self.tts_indicator_var.set("TTS: Muted" if self.mute_tts_var.get() else "TTS: Ready")

    def _set_state(self, state: str) -> None:
        self.state_var.set(state)
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        send_disabled = (
            self.state_var.get() in {"Sending", "Transcribing"}
            or self._recording_mode == "processing"
        )
        self.send_button.configure(state=tk.DISABLED if send_disabled else tk.NORMAL)

        if self._recording_mode in {"starting", "recording"}:
            self.record_button.configure(text="Stop Recording", state=tk.NORMAL)
        elif self._recording_mode == "processing":
            self.record_button.configure(text="Processing...", state=tk.DISABLED)
        elif self.state_var.get() in {"Sending", "Transcribing"}:
            self.record_button.configure(text="Start Recording", state=tk.DISABLED)
        else:
            self.record_button.configure(text="Start Recording", state=tk.NORMAL)

        transcribe_enabled = (
            self._last_recording_result is not None
            and self._recording_mode == "idle"
            and self._transcription_mode != "transcribing"
            and self.state_var.get() != "Sending"
        )
        self.transcribe_button.configure(
            state=tk.NORMAL if transcribe_enabled else tk.DISABLED
        )

    def _append_log(self, speaker: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = format_conversation_log_entry(timestamp, speaker, message)
        self.conversation_log.configure(state=tk.NORMAL)
        self.conversation_log.insert(tk.END, entry)
        self.conversation_log.see(tk.END)
        self.conversation_log.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()
        self._tts.stop()
        self.root.destroy()


def format_conversation_log_entry(timestamp: str, speaker: str, message: str) -> str:
    normalized_message = message.replace("\r\n", "\n").rstrip()
    lines = normalized_message.split("\n") if normalized_message else [""]
    formatted_lines = "\n".join(f"  {line}" if line else "  " for line in lines)
    return f"[{timestamp}] {speaker}:\n{formatted_lines}\n\n"


def format_transcription_summary(result: STTResult) -> str:
    transcription_time = (
        f"{result.transcription_time_seconds:.2f}s"
        if result.transcription_time_seconds is not None
        else "unknown"
    )
    return (
        f"Transcript ready via {result.backend_name} | "
        f"audio_duration={result.duration_seconds:.2f}s | "
        f"transcription_time={transcription_time} | "
        f"model={result.model_name} | "
        f"device={result.device} | "
        f"compute_type={result.compute_type}"
    )
