from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any, Optional, Tuple

from clawtalk.config import AppConfig, ConfigError, load_config
from clawtalk.hotkey import GlobalHotkeyManager, HotkeyError
from clawtalk.logging_setup import configure_logging
from clawtalk.openclaw import (
    OpenClawClient,
    OpenClawError,
    OpenClawResponse,
    create_openclaw_client,
)
from clawtalk.openclaw.ssh_client import resolve_ssh_target
from clawtalk.recorder import (
    AudioRecorder,
    RecorderError,
    RecordingResult,
    format_audio_device,
    format_recording_result,
)
from clawtalk.stt import STTError, STTResult, create_stt_backend
from clawtalk.tts import TTSError, TTSBackend, create_tts_backend


UIEvent = Tuple[str, Any, Any]
logger = logging.getLogger(__name__)

TRANSCRIPT_USER_LABEL = "Me"
TRANSCRIPT_ASSISTANT_LABEL = "Saga"


class MainWindow:
    def __init__(self) -> None:
        configure_logging()
        self.root = tk.Tk()
        self.root.title("ClawTalk")
        self.root.geometry("1080x820")
        self.root.minsize(900, 680)

        self._configure_style()

        self._events: "queue.Queue[UIEvent]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._config: Optional[AppConfig] = None
        self._client: Optional[OpenClawClient] = None
        self._recorder: Optional[AudioRecorder] = None
        self._stt_backend = None
        self._hotkey_manager: Optional[GlobalHotkeyManager] = None
        self._tts: Optional[TTSBackend] = None
        self._recording_mode = "idle"
        self._pending_stop_request = False
        self._transcription_mode = "idle"
        self._last_recording_result: Optional[RecordingResult] = None
        self._last_recording_stopped_at: Optional[float] = None
        self._pending_voice_timing_context: Optional[dict[str, float]] = None

        self.connection_var = tk.StringVar(value="Loading")
        self.state_var = tk.StringVar(value="Starting")
        self.status_line_var = tk.StringVar(value="Starting")
        self.error_var = tk.StringVar(value="")
        self.mute_tts_var = tk.BooleanVar(value=False)
        self.auto_transcribe_var = tk.BooleanVar(value=True)
        self.auto_send_var = tk.BooleanVar(value=True)
        self.debug_mode_var = tk.BooleanVar(value=False)
        self.tts_indicator_var = tk.StringVar(value="Ready")
        self.recording_indicator_var = tk.StringVar(value="Loading microphone")
        self.transport_info_var = tk.StringVar(value="Loading")
        self.gateway_url_var = tk.StringVar(value="Loading")
        self.gateway_token_status_var = tk.StringVar(value="Unknown")
        self.agent_info_var = tk.StringVar(value="Loading")
        self.tts_backend_var = tk.StringVar(value="Loading")
        self.stt_info_var = tk.StringVar(value="Loading")
        self.microphone_var = tk.StringVar(value="Loading")
        self.hotkey_var = tk.StringVar(value="Loading")
        self._transcript_has_messages = False

        self._build_layout()
        self.mute_tts_var.trace_add("write", self._on_mute_changed)
        self.auto_transcribe_var.trace_add("write", self._on_auto_transcribe_changed)
        self.auto_send_var.trace_add("write", self._on_auto_send_changed)
        self.debug_mode_var.trace_add("write", self._on_debug_mode_changed)
        self._load_dependencies()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_events)

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        default_font = ("Segoe UI", 11)
        self.root.option_add("*Font", default_font)
        style = ttk.Style(self.root)
        style.configure("TNotebook.Tab", padding=(16, 10))
        style.configure("Primary.TButton", padding=(16, 10))

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="ClawTalk", font=("Segoe UI Semibold", 22)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Voice-first conversation UI for daily use",
            foreground="#4b5563",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=1, column=0, sticky="nsew")

        self.main_tab = ttk.Frame(self.notebook, padding=14)
        self.settings_tab = ttk.Frame(self.notebook, padding=14)
        self.main_tab.columnconfigure(0, weight=1)
        self.main_tab.rowconfigure(2, weight=1)
        self.settings_tab.columnconfigure(0, weight=1)
        self.settings_tab.rowconfigure(2, weight=1)

        self.notebook.add(self.main_tab, text="Conversation")
        self.notebook.add(self.settings_tab, text="Settings")

        self._build_main_tab()
        self._build_settings_tab()

    def _build_main_tab(self) -> None:
        status_card = ttk.Frame(self.main_tab, padding=(4, 2, 4, 10))
        status_card.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            status_card,
            textvariable=self.status_line_var,
            foreground="#4b5563",
            font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w")

        error_frame = ttk.Frame(self.main_tab)
        error_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        error_frame.columnconfigure(0, weight=1)
        self.error_label = ttk.Label(
            error_frame,
            textvariable=self.error_var,
            foreground="#b42318",
            wraplength=900,
        )
        self.error_label.grid(row=0, column=0, sticky="ew")

        conversation_frame = ttk.LabelFrame(self.main_tab, text="Conversation", padding=12)
        conversation_frame.grid(row=2, column=0, sticky="nsew")
        conversation_frame.columnconfigure(0, weight=1)
        conversation_frame.rowconfigure(0, weight=1)

        self.transcript_display = tk.Text(
            conversation_frame,
            wrap="word",
            state=tk.DISABLED,
            height=22,
            padx=18,
            pady=18,
            font=("Segoe UI", 13),
            spacing1=6,
            spacing2=2,
            spacing3=16,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.transcript_display.grid(row=0, column=0, sticky="nsew")
        self.transcript_display.tag_configure(
            "speaker", font=("Segoe UI Semibold", 13)
        )
        self.transcript_display.tag_configure("placeholder", foreground="#6b7280")

        transcript_scrollbar = ttk.Scrollbar(
            conversation_frame, orient=tk.VERTICAL, command=self.transcript_display.yview
        )
        transcript_scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript_display.configure(yscrollcommand=transcript_scrollbar.set)

        input_frame = ttk.LabelFrame(self.main_tab, text="Message", padding=12)
        input_frame.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        input_frame.columnconfigure(0, weight=1)

        self.message_input = tk.Text(
            input_frame,
            height=5,
            wrap="word",
            padx=10,
            pady=10,
            font=("Segoe UI", 11),
        )
        self.message_input.grid(row=0, column=0, sticky="ew")
        self.message_input.bind("<Control-Return>", self._on_ctrl_enter)

        self.send_button = ttk.Button(
            input_frame,
            text="Send",
            command=self._send_message,
            style="Primary.TButton",
        )
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(12, 0))

        secondary_controls = ttk.Frame(input_frame)
        secondary_controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        secondary_controls.columnconfigure(2, weight=1)

        self.record_button = ttk.Button(
            secondary_controls, text="Start Recording", command=self._toggle_recording
        )
        self.record_button.grid(row=0, column=0, sticky="w")

        self.transcribe_button = ttk.Button(
            secondary_controls,
            text="Transcribe Last Recording",
            command=self._transcribe_last_recording,
            state=tk.DISABLED,
        )
        self.transcribe_button.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.input_hint_label = ttk.Label(
            secondary_controls,
            text="Ctrl+Enter sends",
            foreground="#6b7280",
        )
        self.input_hint_label.grid(row=0, column=3, sticky="e")

    def _build_settings_tab(self) -> None:
        info_frame = ttk.LabelFrame(self.settings_tab, text="Session Info", padding=12)
        info_frame.grid(row=0, column=0, sticky="ew")
        info_frame.columnconfigure(1, weight=1)

        info_rows = [
            ("Transport", self.transport_info_var),
            ("Gateway URL", self.gateway_url_var),
            ("Gateway token", self.gateway_token_status_var),
            ("Agent / model", self.agent_info_var),
            ("TTS backend", self.tts_backend_var),
            ("STT backend", self.stt_info_var),
            ("Microphone", self.microphone_var),
            ("Push-to-talk hotkey", self.hotkey_var),
        ]
        for row_index, (label_text, variable) in enumerate(info_rows):
            ttk.Label(info_frame, text=f"{label_text}:").grid(
                row=row_index, column=0, sticky="nw", padx=(0, 12), pady=4
            )
            ttk.Label(info_frame, textvariable=variable, wraplength=760).grid(
                row=row_index, column=1, sticky="w", pady=4
            )

        controls_frame = ttk.LabelFrame(self.settings_tab, text="Behavior", padding=12)
        controls_frame.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        controls_frame.columnconfigure(0, weight=1)

        self.mute_checkbox = ttk.Checkbutton(
            controls_frame, text="Mute TTS", variable=self.mute_tts_var
        )
        self.mute_checkbox.grid(row=0, column=0, sticky="w", pady=3)

        self.auto_transcribe_checkbox = ttk.Checkbutton(
            controls_frame,
            text="Auto-transcribe after recording",
            variable=self.auto_transcribe_var,
        )
        self.auto_transcribe_checkbox.grid(row=1, column=0, sticky="w", pady=3)

        self.auto_send_checkbox = ttk.Checkbutton(
            controls_frame,
            text="Auto-send after transcription",
            variable=self.auto_send_var,
        )
        self.auto_send_checkbox.grid(row=2, column=0, sticky="w", pady=3)

        self.debug_mode_checkbox = ttk.Checkbutton(
            controls_frame,
            text="Debug mode",
            variable=self.debug_mode_var,
        )
        self.debug_mode_checkbox.grid(row=3, column=0, sticky="w", pady=3)

        ttk.Label(
            controls_frame,
            text="These controls update runtime behavior for the current session. Advanced transport and device settings still come from clawtalk.toml.",
            wraplength=780,
            foreground="#4b5563",
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

        self.debug_frame = ttk.LabelFrame(self.settings_tab, text="Debug Log", padding=12)
        self.debug_frame.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        self.debug_frame.columnconfigure(0, weight=1)
        self.debug_frame.rowconfigure(1, weight=1)

        debug_header = ttk.Frame(self.debug_frame)
        debug_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        debug_header.columnconfigure(0, weight=1)

        self.debug_hint_label = ttk.Label(
            debug_header,
            text="Enable Debug mode to view timing, transport diagnostics, and runtime errors.",
            foreground="#4b5563",
        )
        self.debug_hint_label.grid(row=0, column=0, sticky="w")

        ttk.Button(debug_header, text="Clear Debug Log", command=self._clear_debug_log).grid(
            row=0, column=1, sticky="e"
        )

        self.debug_log = tk.Text(
            self.debug_frame,
            wrap="word",
            state=tk.DISABLED,
            height=14,
            padx=12,
            pady=12,
            font=("Consolas", 10),
            spacing1=2,
            spacing3=4,
        )
        self.debug_log.grid(row=1, column=0, sticky="nsew")

        self.debug_scrollbar = ttk.Scrollbar(
            self.debug_frame, orient=tk.VERTICAL, command=self.debug_log.yview
        )
        self.debug_scrollbar.grid(row=1, column=1, sticky="ns")
        self.debug_log.configure(yscrollcommand=self.debug_scrollbar.set)

        self._refresh_debug_visibility()
        self._show_transcript_placeholder()

    def _load_dependencies(self) -> None:
        try:
            self._config = load_config()
            self._client = create_openclaw_client(self._config)
            self._recorder = AudioRecorder(
                recordings_directory=self._config.recordings_directory or None,
                input_device_index=self._config.input_device_index,
            )
            self._stt_backend = create_stt_backend(self._config)
            self._tts = create_tts_backend(self._config)
            self._tts.set_error_handler(self._post_tts_error)
            self._tts.set_completion_handler(self._post_tts_complete)
        except (ConfigError, STTError, TTSError) as exc:
            self.connection_var.set("Config error")
            self.transport_info_var.set("Config error")
            self._set_state("Error")
            self._set_error(str(exc))
            self._append_log("SYSTEM", str(exc))
            return

        self.mute_tts_var.set(self._config.mute_tts)
        self.auto_transcribe_var.set(self._config.auto_transcribe_after_recording)
        self.auto_send_var.set(self._config.auto_send_after_transcription)
        self.debug_mode_var.set(self._config.debug_mode)

        transport_mode = (self._config.transport.strip().lower() or "ssh")
        if transport_mode == "ssh":
            ssh_target = resolve_ssh_target(
                ssh_target=self._config.ssh_target,
                ssh_user=self._config.ssh_user,
                ssh_host=self._config.ssh_host,
            )
        else:
            ssh_target = ""

        connection_summary = format_connection_summary(self._config, ssh_target)
        self.connection_var.set(connection_summary)
        self.transport_info_var.set(connection_summary)
        self.gateway_url_var.set(self._config.gateway_url.strip() or "Not configured")
        self.gateway_token_status_var.set(masked_secret_status(self._config.gateway_token))
        self.agent_info_var.set(get_agent_summary(self._config))
        self.tts_backend_var.set(get_tts_summary(self._config))
        self.stt_info_var.set(get_stt_summary(self._config))
        self.hotkey_var.set(self._config.push_to_talk_hotkey)
        self._set_state("Idle")

        self._append_log("SYSTEM", "Configuration loaded. Ready to send messages.")
        self._append_log(
            "SYSTEM",
            f"Voice defaults: auto_transcribe={self.auto_transcribe_var.get()} | auto_send={self.auto_send_var.get()} | debug_mode={self.debug_mode_var.get()}",
        )
        self._append_log(
            "SYSTEM",
            f"Transport configured: {connection_summary}",
        )
        self._append_log(
            "SYSTEM",
            f"TTS backend: {self._config.tts_backend}",
        )
        self._update_tts_indicator()
        self._initialize_recording_status()
        self._initialize_hotkey()
        self._sync_auto_send_checkbox()

    def _initialize_recording_status(self) -> None:
        if self._recorder is None or self._config is None:
            self.recording_indicator_var.set("Recorder unavailable")
            self.microphone_var.set("Recorder unavailable")
            return

        try:
            devices = self._recorder.get_available_input_devices()
            for device in devices:
                logger.info("Audio input device: %s", format_audio_device(device))
            selected_device = self._recorder.get_selected_input_device()
            self.recording_indicator_var.set(
                f"{selected_device.name} | PTT: {self._config.push_to_talk_hotkey}"
            )
            self.microphone_var.set(
                f"[{selected_device.index}] {selected_device.name}"
            )
            self._append_log(
                "SYSTEM",
                f"Selected input device: [{selected_device.index}] {selected_device.name}",
            )
            self._update_tts_indicator()
        except RecorderError as exc:
            self.recording_indicator_var.set("Microphone error")
            self.microphone_var.set("Error")
            self._append_log("RECORDER ERROR", str(exc))
            self._set_error(str(exc))
            self._update_tts_indicator()

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
            self._set_error(str(exc))

    def _on_ctrl_enter(self, event: tk.Event) -> str:
        self._send_message()
        return "break"

    def _send_message(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        if self._recording_mode in {"starting", "recording", "processing"}:
            self._append_log("SYSTEM", "Finish the current recording before sending.")
            self._set_error("Finish the current recording before sending.")
            return
        if self._transcription_mode == "transcribing":
            self._append_log("SYSTEM", "Wait for the current transcription to finish.")
            self._set_error("Wait for the current transcription to finish.")
            return
        if self._client is None:
            self._append_log("SYSTEM", "Cannot send message until config loads successfully.")
            self._set_state("Error")
            self._set_error("Cannot send message until config loads successfully.")
            return

        message = self.message_input.get("1.0", tk.END).strip()
        if not message:
            self._set_state("Error")
            self._set_error("Type a message before sending.")
            self._append_log("SYSTEM", "Please enter a message before sending.")
            return

        self._send_text_message(message)

    def _send_text_message(self, message: str) -> None:
        self._clear_error()
        self._append_transcript_message(TRANSCRIPT_USER_LABEL, message)
        self._set_state("Sending")
        self._worker = threading.Thread(
            target=self._send_message_worker, args=(message,), daemon=True
        )
        self._worker.start()

    def _send_message_worker(self, message: str) -> None:
        try:
            assert self._client is not None
            response = self._client.send_message_details(message)
        except OpenClawError as exc:
            self._events.put(("error", str(exc), ""))
            return
        except Exception as exc:  # pragma: no cover
            self._events.put(("error", f"Unexpected error: {exc}", ""))
            return

        self._events.put(("reply", message, response))

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
            self._set_error("Cannot start recording while a send is in progress.")
            return
        if self._transcription_mode == "transcribing":
            self._append_log("SYSTEM", "Cannot start recording while transcription is in progress.")
            self._set_error("Cannot start recording while transcription is in progress.")
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
            self._set_error("Recorder is not available.")
            return
        if self._recorder.is_recording():
            logger.warning(
                "Recorder reported an active session before start. source=%s mode=%s",
                source,
                self._recording_mode,
            )
            self._recording_mode = "recording"
            self._set_state("Listening")
            return

        self._recording_mode = "starting"
        self._pending_stop_request = False
        self._clear_error()
        self._set_state("Listening")
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
        self._set_state("Listening")
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
        self._begin_transcription(auto_triggered=False)

    def _begin_transcription(self, auto_triggered: bool) -> None:
        if self._transcription_mode == "transcribing":
            return
        if self._last_recording_result is None:
            self._append_log("SYSTEM", "Record audio before transcribing.")
            self._set_error("Record audio before transcribing.")
            return
        if not self._last_recording_result.file_path.exists():
            self._handle_error(f"Recording file not found: {self._last_recording_result.file_path}")
            return
        if self._stt_backend is None:
            self._handle_error("Speech-to-text backend is not configured.")
            return

        self._clear_error()
        self._transcription_mode = "transcribing"
        self._set_state("Transcribing")
        threading.Thread(
            target=self._transcribe_last_recording_worker,
            args=(auto_triggered,),
            daemon=True,
        ).start()

    def _transcribe_last_recording_worker(self, auto_triggered: bool) -> None:
        try:
            assert self._last_recording_result is not None
            assert self._stt_backend is not None
            logger.info(
                "Starting transcription worker. path=%s backend=%s auto_triggered=%s",
                self._last_recording_result.file_path,
                self._config.stt_backend if self._config is not None else "unknown",
                auto_triggered,
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

        self._events.put(("transcription_complete", result, auto_triggered))

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
                self._set_error(first)
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
                self._set_error(first)
            elif event_type == "transcription_complete":
                self._handle_transcription_complete(first, bool(second))
            elif event_type == "transcription_error":
                self._handle_transcription_error(first)

        self.root.after(100, self._drain_events)

    def _handle_reply(self, message: str, response: OpenClawResponse) -> None:
        del message
        reply = response.reply_text
        self._append_transcript_message(TRANSCRIPT_ASSISTANT_LABEL, reply)
        self.message_input.delete("1.0", tk.END)
        self._clear_error()
        reply_displayed_at = time.perf_counter()
        transport_label = "gateway" if response.transport_name == "gateway" else "openclaw"
        timing_parts = [f"{transport_label}={response.duration_seconds:.2f}s"]

        if not self.mute_tts_var.get():
            self._set_state("Speaking")
            logger.info("TTS request queued from UI. text_length=%s", len(reply))
            assert self._tts is not None
            self._tts.speak_async(reply)
            tts_queued_at = time.perf_counter()
        else:
            logger.info("TTS muted/skipped for reply. text_length=%s", len(reply))
            self._set_state("Idle")
            tts_queued_at = None

        if self._pending_voice_timing_context is not None:
            stop_to_reply = (
                reply_displayed_at
                - self._pending_voice_timing_context["recording_stopped_at"]
            )
            timing_parts.append(f"stop->reply={stop_to_reply:.2f}s")
            if tts_queued_at is not None:
                stop_to_tts = (
                    tts_queued_at
                    - self._pending_voice_timing_context["recording_stopped_at"]
                )
                timing_parts.append(f"stop->tts={stop_to_tts:.2f}s")
            stt_duration = self._pending_voice_timing_context.get("stt_duration_seconds")
            if stt_duration is not None:
                timing_parts.append(f"stt={stt_duration:.2f}s")
            logger.info(
                "Voice interaction timing. transport=%s duration=%.3fs stt=%s stop_to_reply=%.3fs stop_to_tts=%s returncode=%s output_length=%s error_length=%s",
                response.transport_name,
                response.duration_seconds,
                (
                    f"{self._pending_voice_timing_context.get('stt_duration_seconds'):.3f}s"
                    if self._pending_voice_timing_context.get("stt_duration_seconds") is not None
                    else "n/a"
                ),
                stop_to_reply,
                (
                    f"{stop_to_tts:.3f}s" if tts_queued_at is not None else "n/a"
                ),
                response.return_code,
                response.output_length,
                response.error_length,
            )
            self._pending_voice_timing_context = None
        else:
            logger.info(
                "Text interaction timing. transport=%s duration=%.3fs returncode=%s output_length=%s error_length=%s",
                response.transport_name,
                response.duration_seconds,
                response.return_code,
                response.output_length,
                response.error_length,
            )

        self._append_log("TIMING", " | ".join(timing_parts))

    def _handle_error(self, error_message: str) -> None:
        self._append_log("ERROR", error_message)
        self._set_error(error_message)
        self._set_state("Error")

    def _handle_recording_started(self, source: str, device_name: str) -> None:
        self._recording_mode = "recording"
        if self._config is not None:
            self.recording_indicator_var.set(
                f"{device_name} | PTT: {self._config.push_to_talk_hotkey}"
            )
            self._update_tts_indicator()
        self._append_log("RECORDER", f"Recording started via {source}. input={device_name}")
        self._refresh_controls()
        if self._pending_stop_request:
            self._pending_stop_request = False
            self._request_stop_recording(source)

    def _handle_recording_saved(self, source: str, result: RecordingResult) -> None:
        self._recording_mode = "idle"
        self._last_recording_result = result
        self._last_recording_stopped_at = time.perf_counter()
        self._set_state("Idle")
        self._append_log("RECORDER", f"Recording stopped via {source}.")
        self._append_log("RECORDER", format_recording_result(result))
        if result.stats.appears_silent:
            self._set_error(
                "Recording saved, but it appears silent. Check the selected input device."
            )
        if should_auto_transcribe_recording(self.auto_transcribe_var.get(), result):
            self._append_log("SYSTEM", "Auto-transcribe enabled; transcribing last recording.")
            self._begin_transcription(auto_triggered=True)

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
        self.recording_indicator_var.set(f"Error | {display_message}")
        self._update_tts_indicator()
        self._set_error(display_message)
        self._append_log("RECORDER ERROR", f"{source}: {display_message}")
        self._set_state("Error")

    def _handle_transcription_complete(self, result: STTResult, auto_triggered: bool) -> None:
        self._transcription_mode = "idle"
        if result.transcript_text:
            self._set_message_input(result.transcript_text)
        else:
            self._set_error("Transcription completed, but no speech was detected.")

        self._append_log("STT", format_transcription_summary(result))
        if result.transcription_time_seconds is not None:
            self._append_log("TIMING", f"stt={result.transcription_time_seconds:.2f}s")
        if result.model_load_time_seconds is not None:
            self._append_log("TIMING", f"stt_model_load={result.model_load_time_seconds:.2f}s")
        if result.diagnostics:
            self._append_log("STT", " | ".join(result.diagnostics))

        auto_send, reason = should_auto_send_transcript(
            self.auto_send_var.get(),
            self._last_recording_result,
            result,
        )
        if auto_triggered and auto_send:
            self._append_log("SYSTEM", "Auto-send enabled; sending transcript to OpenClaw.")
            if self._last_recording_stopped_at is not None:
                self._pending_voice_timing_context = {
                    "recording_stopped_at": self._last_recording_stopped_at,
                    "stt_duration_seconds": (
                        result.transcription_time_seconds
                        if result.transcription_time_seconds is not None
                        else 0.0
                    ),
                }
            self._set_state("Idle")
            self._send_text_message(result.transcript_text.strip())
            return
        if auto_triggered and self.auto_send_var.get() and reason:
            self._append_log("SYSTEM", f"Auto-send skipped: {reason}")
            if not result.transcript_text.strip():
                self._set_error("Transcript was empty, so nothing was sent.")

        self._set_state("Idle")

    def _handle_transcription_error(self, error_message: str) -> None:
        self._transcription_mode = "idle"
        self._set_error(error_message)
        self._append_log("STT ERROR", error_message)
        self._set_state("Error")

    def _post_tts_error(self, message: str) -> None:
        self._events.put(("tts_error", message, ""))

    def _post_tts_complete(self) -> None:
        self._events.put(("tts_complete", "", ""))

    def _post_hotkey_error(self, message: str) -> None:
        self._events.put(("hotkey_error", message, ""))

    def _set_message_input(self, value: str) -> None:
        self.message_input.delete("1.0", tk.END)
        self.message_input.insert("1.0", value)

    def _clear_debug_log(self) -> None:
        self.debug_log.configure(state=tk.NORMAL)
        self.debug_log.delete("1.0", tk.END)
        self.debug_log.configure(state=tk.DISABLED)
        self._append_log("SYSTEM", "Debug log cleared.")

    def _on_mute_changed(self, *_args: object) -> None:
        self._update_tts_indicator()

    def _on_auto_transcribe_changed(self, *_args: object) -> None:
        self._sync_auto_send_checkbox()

    def _on_auto_send_changed(self, *_args: object) -> None:
        if self.auto_send_var.get() and not self.auto_transcribe_var.get():
            self.auto_transcribe_var.set(True)
        self._sync_auto_send_checkbox()

    def _on_debug_mode_changed(self, *_args: object) -> None:
        self._refresh_debug_visibility()
        self._append_log(
            "SYSTEM",
            f"Debug mode {'enabled' if self.debug_mode_var.get() else 'disabled'}.",
        )

    def _sync_auto_send_checkbox(self) -> None:
        if not self.auto_transcribe_var.get():
            self.auto_send_var.set(False)
            self.auto_send_checkbox.configure(state=tk.DISABLED)
        else:
            self.auto_send_checkbox.configure(state=tk.NORMAL)

    def _update_tts_indicator(self) -> None:
        backend_name = self._tts.backend_name if self._tts is not None else "unknown"
        self.tts_indicator_var.set(backend_name)
        self._update_status_line()

    def _set_state(self, state: str) -> None:
        self.state_var.set(state)
        self._update_status_line()
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
        if self.auto_transcribe_var.get():
            self.transcribe_button.configure(style="TButton")
        else:
            self.transcribe_button.configure(style="Primary.TButton")

    def _append_transcript_message(self, speaker_label: str, message: str) -> None:
        entry = format_transcript_entry(speaker_label, message)
        if not self._transcript_has_messages:
            self._clear_transcript_display()
            self._transcript_has_messages = True
        self.transcript_display.configure(state=tk.NORMAL)
        prefix, body = entry.split(": ", 1)
        self.transcript_display.insert(tk.END, prefix + ": ", ("speaker",))
        self.transcript_display.insert(tk.END, body)
        self.transcript_display.see(tk.END)
        self.transcript_display.configure(state=tk.DISABLED)

    def _append_log(self, speaker: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = format_debug_log_entry(timestamp, speaker, message)
        self.debug_log.configure(state=tk.NORMAL)
        self.debug_log.insert(tk.END, entry)
        self.debug_log.see(tk.END)
        self.debug_log.configure(state=tk.DISABLED)

    def _refresh_debug_visibility(self) -> None:
        debug_visible = should_show_debug_controls(self.debug_mode_var.get())
        if debug_visible:
            self.debug_log.grid()
            self.debug_scrollbar.grid()
            self.debug_hint_label.configure(
                text="Debug mode is on. Timing, transport diagnostics, STT, TTS, and runtime errors are shown below."
            )
        else:
            self.debug_log.grid_remove()
            self.debug_scrollbar.grid_remove()
            self.debug_hint_label.configure(
                text="Enable Debug mode to view timing, transport diagnostics, and runtime errors."
            )

    def _set_error(self, message: str) -> None:
        self.error_var.set(message.strip())

    def _clear_error(self) -> None:
        self.error_var.set("")

    def _show_transcript_placeholder(self) -> None:
        self._clear_transcript_display()
        self.transcript_display.configure(state=tk.NORMAL)
        self.transcript_display.insert(
            "1.0",
            "Hold push-to-talk or type a message to start.",
            ("placeholder",),
        )
        self.transcript_display.configure(state=tk.DISABLED)
        self._transcript_has_messages = False

    def _clear_transcript_display(self) -> None:
        self.transcript_display.configure(state=tk.NORMAL)
        self.transcript_display.delete("1.0", tk.END)
        self.transcript_display.configure(state=tk.DISABLED)

    def _update_status_line(self) -> None:
        state = self.state_var.get() or "Idle"
        hotkey = self.hotkey_var.get() or "loading"
        tts_backend = self.tts_indicator_var.get() or "unknown"
        mic_name = self.recording_indicator_var.get() or "loading"
        if " | PTT:" in mic_name:
            mic_name = mic_name.split(" | PTT:", 1)[0]
        self.status_line_var.set(
            f"{state} | PTT: {hotkey} | TTS: {tts_backend} | Mic: {mic_name}"
        )

    def _on_close(self) -> None:
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()
        if self._tts is not None:
            self._tts.stop()
        self.root.destroy()


def format_transcript_entry(speaker_label: str, message: str) -> str:
    normalized_message = message.replace("\r\n", "\n").rstrip()
    if not normalized_message:
        normalized_message = ""
    lines = normalized_message.split("\n") if normalized_message else [""]
    first_line = f"{speaker_label}: {lines[0]}"
    if len(lines) == 1:
        return first_line + "\n\n"
    continuation = "\n".join(lines[1:])
    return f"{first_line}\n{continuation}\n\n"


def format_debug_log_entry(timestamp: str, speaker: str, message: str) -> str:
    normalized_message = message.replace("\r\n", "\n").rstrip()
    lines = normalized_message.split("\n") if normalized_message else [""]
    formatted_lines = "\n".join(f"  {line}" if line else "  " for line in lines)
    return f"[{timestamp}] {speaker}:\n{formatted_lines}\n\n"


def format_conversation_log_entry(timestamp: str, speaker: str, message: str) -> str:
    return format_debug_log_entry(timestamp, speaker, message)


def format_transcription_summary(result: STTResult) -> str:
    transcription_time = (
        f"{result.transcription_time_seconds:.2f}s"
        if result.transcription_time_seconds is not None
        else "unknown"
    )
    model_name = result.model_name or "unknown"
    device = result.device or "unknown"
    compute_type = result.compute_type or "unknown"
    return (
        f"Transcript ready via {result.backend_name} | "
        f"audio_duration={result.duration_seconds:.2f}s | "
        f"transcription_time={transcription_time} | "
        f"model={model_name} | "
        f"device={device} | "
        f"compute_type={compute_type}"
    )


def should_auto_transcribe_recording(
    auto_transcribe_enabled: bool, recording_result: Optional[RecordingResult]
) -> bool:
    return auto_transcribe_enabled and recording_result is not None


def should_auto_send_transcript(
    auto_send_enabled: bool,
    recording_result: Optional[RecordingResult],
    transcription_result: STTResult,
) -> Tuple[bool, str]:
    if not auto_send_enabled:
        return False, "Auto-send is disabled."
    if recording_result is None:
        return False, "No recording is available."
    if recording_result.stats.appears_silent:
        return False, "Recording appears silent."
    if not transcription_result.transcript_text.strip():
        return False, "Transcript was empty."
    return True, ""


def should_show_debug_controls(debug_mode_enabled: bool) -> bool:
    return debug_mode_enabled


def format_connection_summary(config: AppConfig, ssh_target: str) -> str:
    transport = config.transport.strip().lower() or "ssh"
    if transport == "gateway":
        agent = config.gateway_agent.strip() or config.openclaw_agent
        gateway_url = config.gateway_url.strip() or "not configured"
        return f"gateway: {gateway_url} (agent: {agent})"
    return f"{ssh_target} (agent: {config.openclaw_agent})"


def masked_secret_status(secret_value: str) -> str:
    return "configured" if secret_value.strip() else "missing"


def get_agent_summary(config: AppConfig) -> str:
    transport = config.transport.strip().lower() or "ssh"
    if transport == "gateway":
        return config.gateway_agent.strip() or config.openclaw_agent
    return config.openclaw_agent


def get_tts_summary(config: AppConfig) -> str:
    summary = config.tts_backend
    if config.tts_backend == "openai":
        key_status = masked_secret_status(os.environ.get(config.openai_tts_api_key_env, ""))
        summary = (
            f"{config.tts_backend} | model={config.openai_tts_model} | "
            f"voice={config.openai_tts_voice} | key={key_status}"
        )
    return summary


def get_stt_summary(config: AppConfig) -> str:
    return (
        f"{config.stt_backend} | model={config.whisper_model_size} | "
        f"device={config.whisper_device} | compute={config.whisper_compute_type}"
    )
