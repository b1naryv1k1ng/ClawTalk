# ClawTalk

ClawTalk is a Windows desktop MVP for talking to an OpenClaw agent from a simple local app. The current implementation now supports a full local voice loop and presents it in a conversation-first UI for normal daily use: hold push-to-talk, let ClawTalk transcribe and send automatically, read the transcript, and hear Saga speak the reply.

## Current MVP Status

- Phase 1 implemented: text input, SSH request to OpenClaw, visible reply, and TTS playback.
- Phase 3 implemented: local WAV recording with a button and global push-to-talk hotkey.
- Phase 4 implemented: transcribe the most recent recording into the manual message box for review and editing.
- Phase 5 implemented: auto-transcribe and auto-send voice loop after recording, enabled by default.

## Why `tkinter`

This MVP uses `tkinter` because it ships with Python on Windows and keeps the dependency burden small while we validate the core SSH and TTS loop first.

## Project Layout

```text
clawtalk/
  app.py
  config.py
  logging_setup.py
  hotkey.py
  recorder.py
  stt/
    __init__.py
    base.py
    faster_whisper_backend.py
    placeholder_backend.py
  tts/
    __init__.py
    base.py
    openai_tts.py
    windows_tts.py
  openclaw/
    __init__.py
    base.py
    gateway_client.py
    ssh_client.py
  ui/
    __init__.py
    main_window.py
  gateway_probe.py
  tts_test.py
requirements.txt
README.md
clawtalk.example.toml
.gitignore
```

## Windows Setup

### Recommended Python Version

- Recommended: Python 3.11 or newer on Windows 11
- Tested structure compatibility: Python 3.8+

### Install Dependencies

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure ClawTalk

1. Copy the example config:

```powershell
Copy-Item clawtalk.example.toml clawtalk.toml
```

2. Edit `clawtalk.toml` if you need to change advanced settings such as transport, gateway URL, agent, microphone device index, hotkey, STT backend, or TTS backend.

Default values:

- `transport = "ssh"`
- `ssh_target = "eitri-openclaw"`
- `ssh_host = "eitri"`
- `ssh_user = "openclaw"`
- `openclaw_agent = "main"`
- `openclaw_command_template = "openclaw agent --agent {agent} --message {message}"`
- `gateway_url = "http://127.0.0.1:18789"`
- `gateway_token = ""`
- `gateway_agent = "openclaw/saga"`
- `gateway_timeout_seconds = 60`
- `tts_backend = "windows"`
- `openai_tts_model = "gpt-4o-mini-tts"`
- `openai_tts_voice = "sage"`
- `openai_tts_format = "wav"`
- `openai_tts_api_key_env = "OPENAI_API_KEY"`
- `openai_tts_timeout_seconds = 60`
- `openai_tts_fallback_to_windows = false`
- `push_to_talk_hotkey = "ctrl+shift+f9"`
- `recordings_directory = ""`
- `input_device_index` omitted uses the system default microphone
- `stt_backend = "faster_whisper"`
- `whisper_model_size = "base"`
- `whisper_device = "auto"`
- `whisper_compute_type = "auto"`
- `auto_transcribe_after_recording = true`
- `auto_send_after_transcription = true`
- `debug_mode = false`

### Configure SSH Access to Eitri / OpenClaw

- Make sure Windows OpenSSH Client is installed.
- Make sure `ssh` works from PowerShell.
- Set up SSH key authentication separately before debugging the app.
- Confirm the `openclaw` user on `eitri` can run the `openclaw agent ...` command.
- Prefer using a Windows SSH config alias so the app can call a stable target name.

Example `C:\Users\<you>\.ssh\config` entry:

```sshconfig
Host eitri-openclaw
    HostName eitri
    User openclaw
    IdentityFile C:\Users\<you>\.ssh\id_ed25519
```

- With `ssh_target` set, ClawTalk uses that alias and ignores `ssh_user` / `ssh_host`.
- If `ssh_target` is blank, ClawTalk falls back to `ssh_user@ssh_host`.

### Manual OpenClaw SSH Test

Run this first to confirm OpenClaw itself is reachable before debugging the app:

```powershell
ssh eitri-openclaw "openclaw agent --agent main --message 'Say this is working in one sentence.'"
```

Successful result from PowerShell:

```text
This is working.
```

## Normal Mode vs Debug Mode

- Normal mode is the default. The `Conversation` tab stays focused on the transcript, text input, send button, and voice controls.
- Debug mode is off by default. Timing lines, transport diagnostics, STT details, TTS details, and runtime errors move into the `Settings` tab under `Debug Log`.
- Advanced runtime info such as transport, agent/model, microphone, TTS backend, push-to-talk hotkey, and voice behavior toggles also lives in the `Settings` tab.
- Secrets are never shown directly in the UI. Token state is shown only as `configured` or `missing`.

## Run The App

From the repo root:

```powershell
python -m clawtalk.app
```

Daily-use UI notes:

- Use the `Conversation` tab for normal chatting.
- Use push-to-talk as the primary voice input.
- Use the `Settings` tab for advanced controls and the optional debug log.

Developer TTS smoke test:

```powershell
python -m clawtalk.tts.windows_tts_test
```

Config-aware TTS backend test:

```powershell
python -m clawtalk.tts_test "Hello, this is Saga."
```

List available input devices:

```powershell
python -m clawtalk.recorder_devices
```

Standalone transcription diagnostic:

```powershell
python -m clawtalk.stt_test path\to\recording.wav
```

Gateway transport probe:

```powershell
python -m clawtalk.gateway_probe
```

## What Works In Phase 1

- Local desktop window titled `ClawTalk`
- Manual text input and `Send` button
- SSH-based OpenClaw request execution
- SSH remains the default stable transport
- Safe quoting for the agent name and user message inside the remote command template
- SSH config alias support through `ssh_target`
- Clean scrolling conversation transcript with `Me:` and `Saga:` lines
- Windows TTS playback through `pyttsx3`
- Pluggable TTS backends with Windows TTS as the default fallback
- Runtime settings tab for mute, auto-transcribe, auto-send, and debug mode
- Advanced transport and device visibility in the UI without exposing secrets
- Background threads for SSH and TTS so the UI does not block during those tasks

## Phase 2 Polish

- Clearer status panel showing connection, current state, and TTS mute state
- `Clear Log` button
- `Ctrl+Enter` sends from the message box
- `Send` stays disabled while an SSH request is in progress
- Improved spacing and readability in the main window and conversation view
- No `Stop Speaking` button yet because the current background `pyttsx3` pattern is stable for playback, but safe cross-thread cancellation is not reliable enough for this MVP

## Phase 3 Push-To-Talk Shell

- `Start Recording` button toggles microphone capture for local testing
- Global push-to-talk hotkey defaults to `Ctrl+Shift+F9`
- Holding the hotkey starts recording and releasing it stops recording
- Recordings are saved as `.wav` files in the system temp directory by default
- Recording diagnostics are logged with input device, duration, file path, file size, peak amplitude, and RMS level

## Phase 4 Transcription

- `Transcribe Last Recording` runs local STT on the latest saved WAV
- Transcript text is placed into the existing manual message box
- You can edit the transcript before manually clicking `Send`
- Transcription runs in a background worker so the UI stays responsive
- Recorded WAV files can stay at 48000 Hz; the STT backend handles the file as-is

## Phase 5 Voice Loop

- Optional `Auto-transcribe after recording` checkbox
- Optional `Auto-send after transcription` checkbox
- Auto-send only runs after a successful transcription
- Silent recordings and empty transcripts are not auto-sent
- The app logs before auto-send so the behavior stays visible

Current defaults:

- `Auto-transcribe after recording` starts enabled
- `Auto-send after transcription` starts enabled
- Turn them off in the `Settings` tab if you want a slower manual review loop for the current session

## What Is Still TODO

- Streaming or partial responses
- Persistent conversation history
- Tray behavior and packaging

## Known MVP Limitations

- The app currently sends one request at a time.
- SSH output is treated as a single final reply, not a streamed response.
- TTS state is approximate in this MVP and does not yet track exact playback completion.
- Auto-send starts on by default now, but you may still want to turn it off temporarily while tuning your microphone and transcript quality.
- Config is file-based only and edited outside the app.
- No installer or packaged `.exe` yet.

## Phase 3 Usage

- Run `python -m clawtalk.recorder_devices` to list microphone-capable input devices.
- If Windows default input is wrong, set `input_device_index` in `clawtalk.toml` to the desired device index.
- Click `Start Recording` to begin a local WAV recording.
- Click `Stop Recording` to save it.
- Or hold `Ctrl+Shift+F9` anywhere on Windows to start recording and release it to stop.
- Turn on `Debug mode` in the `Settings` tab if you want to inspect the saved file path, duration, file size, peak amplitude, and RMS level.
- If you want a custom output folder, set `recordings_directory` in `clawtalk.toml`.

## Phase 4 Usage

- Record audio with the button or `Ctrl+Shift+F9`.
- Click `Transcribe Last Recording`.
- Wait for the state to move through `Transcribing` and back to `Idle`.
- Review and edit the transcript in the message box.
- Click `Send` manually when you are ready.

## Phase 5 Usage

- Manual mode:
  Turn both auto options off in the `Settings` tab. Recording, transcription, and sending stay manual.
- Auto-transcribe mode:
  Leave `Auto-transcribe after recording` on and turn `Auto-send after transcription` off.
  After each recording, ClawTalk transcribes into the message box but does not send.
- Full auto-send voice loop:
  Leave both defaults enabled.
  After recording, ClawTalk transcribes, sends the transcript to OpenClaw, displays the reply, and speaks it.
- Recommendation:
  If you are still tuning your microphone or STT accuracy, turn off auto-send temporarily in the `Settings` tab.

## TTS Backends

### Windows TTS

- Default backend
- Uses built-in Windows speech through `pyttsx3`
- Lowest setup burden and the easiest fallback

### OpenAI TTS

- Experimental backend for higher-quality speech
- Uses the OpenAI Audio speech endpoint
- Reads the API key from an environment variable only
- Saves generated audio to a temp file and plays it locally
- Supports `wav` and `mp3` output formats
- Can optionally fall back to Windows TTS if `openai_tts_fallback_to_windows = true`

PowerShell example for the current shell session:

```powershell
$env:OPENAI_API_KEY = "your-api-key-here"
```

Example config:

```toml
tts_backend = "openai"
openai_tts_model = "gpt-4o-mini-tts"
openai_tts_voice = "sage"
openai_tts_format = "wav"
openai_tts_api_key_env = "OPENAI_API_KEY"
openai_tts_timeout_seconds = 60
openai_tts_fallback_to_windows = false
```

To switch back to Windows TTS:

```toml
tts_backend = "windows"
```

## Transport Modes

### SSH Transport

- Stable and default for the current MVP
- Works well with the existing `ssh_target = "eitri-openclaw"` alias over Tailscale
- This is still the active transport used by the UI today

### Gateway Transport

- Experimental, and usually faster than the SSH CLI path when the local OpenClaw HTTP Gateway is enabled
- Config entries exist for future work:
  - `transport = "gateway"`
  - `gateway_url`
  - `gateway_token`
  - `gateway_agent`
- Current experimental HTTP path uses:
  - `POST /v1/chat/completions`
  - `Authorization: Bearer <gateway token>`
  - OpenAI-style JSON response parsing from `choices[0].message.content`
- OpenClaw HTTP endpoint settings to enable on Eitri:
  - `gateway.http.endpoints.chatCompletions.enabled = true`
  - `gateway.http.endpoints.responses.enabled = true`
- Gateway auth uses a bearer token in `gateway_token`
- The probe command checks `/v1/models` and then sends a tiny test request to the configured `gateway_agent`
- ClawTalk currently implements the HTTP `/v1/chat/completions` path only
- Gateway Responses and any future WebSocket/RPC transport are still separate follow-up work
- WebSocket RPC is still not implemented in ClawTalk
- Keep the Gateway listener private:
  - loopback on Eitri
  - SSH tunnel
  - Tailscale/private network only
- Do not bind an OpenClaw Gateway to `0.0.0.0`

## Faster-Whisper Notes

- `faster-whisper` is used for local transcription in this phase.
- The model loads lazily the first time you transcribe, so the first run can be noticeably slower.
- The first model load/download can take time depending on your connection and model size.
- The loaded model is reused for the rest of the app session.
- 48000 Hz WAV recordings are expected and okay; the backend handles them without requiring recorder-side resampling.

## Troubleshooting

### Config File Missing

- If the app says the config is missing, copy `clawtalk.example.toml` to `clawtalk.toml`.

### `ssh` Command Not Found

- Install the Windows OpenSSH Client feature.
- Restart your terminal after installation.
- Verify `ssh` works from PowerShell directly.

### OpenClaw Command Fails Over SSH

- Run the manual SSH test command above.
- If you use an SSH alias, verify `ssh eitri-openclaw` works outside the app first.
- Verify the `openclaw` command exists on the remote host.
- Verify the configured agent name is valid.
- Check that your SSH key auth works without interactive prompts.
- ClawTalk forces UTF-8 decoding for SSH output so smart punctuation should display correctly even on Windows systems with a non-UTF-8 default code page.

### Gateway Probe Fails

- If you are on an older ClawTalk build, upgrade first.
- In the current build, `python -m clawtalk.gateway_probe` calls `/v1/models` and a small `/v1/chat/completions` request.
- If it fails, confirm:
  - `gateway_url` points at the running local Gateway
  - `gateway_token` is valid
  - `gateway.http.endpoints.chatCompletions.enabled = true`
  - `gateway.http.endpoints.responses.enabled = true`

### TTS Fails

- Confirm Windows audio output is working.
- Reinstall the Python dependencies in your virtual environment.
- Try muting TTS in the app to confirm SSH and UI still work separately.

### OpenAI TTS Fails

- Confirm the API key environment variable named by `openai_tts_api_key_env` is set before launching ClawTalk.
- Run `python -m clawtalk.tts_test "Hello, this is Saga."` to test the configured backend outside the main app flow.
- Reinstall dependencies with `pip install -r requirements.txt` so `pygame` is available for local playback.
- If you want the old behavior immediately, set `tts_backend = "windows"` in `clawtalk.toml`.
- If `openai_tts_fallback_to_windows = true`, ClawTalk will try the Windows backend after an OpenAI TTS failure.

### TTS Only Speaks Once

- Run `python -m clawtalk.tts.windows_tts_test` to verify repeated local playback outside the main UI flow.
- If that fails, reinstall `pyttsx3` in your active virtual environment and relaunch the app.
- Watch the app status and debug log for `TTS ERROR` messages after a send.

### Recording Fails

- Make sure your microphone is connected and selected as the default Windows input device.
- Check that Windows microphone permissions allow desktop apps to access the mic.
- Reinstall dependencies with `pip install -r requirements.txt` to ensure `sounddevice` is available.
- Watch the debug log for `RECORDER ERROR` messages describing startup, permission, or zero-length issues.

### Recordings Are Silent

- Run `python -m clawtalk.recorder_devices` and verify the correct headset microphone index is listed as an input device.
- If the default device is wrong, set `input_device_index` in `clawtalk.toml` and restart the app.
- After recording, enable `Debug mode` and check the debug log for `peak=` and `rms=` diagnostics.
- If the log shows `WARNING: recording appears silent`, ClawTalk captured near-zero samples even though the WAV was written.
- Avoid monitor/output devices and pick a device with real input channels, such as your Logitech headset microphone.

### Transcription Dependency Missing

- Install dependencies again with `pip install -r requirements.txt`.
- Verify `faster-whisper` is present in the same virtual environment you use to run ClawTalk.
- Run `python -m clawtalk.stt_test path\to\recording.wav` to test transcription outside the UI.

### Model Download Or Load Is Slow

- The first transcription can take longer because the model may need to download and initialize.
- Try a smaller `whisper_model_size` such as `small` or `tiny` if you want faster startup.

### Quiet Mic Or Bad Transcript

- A quiet recording usually leads to a weaker transcript.
- Check Windows input volume and headset microphone gain.
- Review the recording diagnostics in the debug log for `peak=` and `rms=` values.
- 48000 Hz WAVs are expected and do not need to be manually converted before transcription.

### Auto-Send Did Not Trigger

- Auto-send only works when `Auto-transcribe after recording` is enabled.
- Silent recordings are not auto-sent.
- Empty transcripts are not auto-sent.
- If transcription fails, nothing is sent.
- Turn on `Debug mode` and check the debug log for `Auto-send enabled` or `Auto-send skipped` messages.

### Push-To-Talk Hotkey Fails

- Verify `pynput` is installed in the same virtual environment as ClawTalk.
- Some Windows environments or security tools may block global keyboard hooks.
- Windows may emit repeated keydown events while a key is held. ClawTalk latches the hotkey state so one hold should create exactly one recording until release.
- If hotkey registration fails, the `Start Recording` button still works for local testing.
- If needed, change `push_to_talk_hotkey` in `clawtalk.toml` and restart the app.

## Future Upgrade Path

- Direct OpenClaw Gateway access over Tailscale instead of SSH
- WebSocket/RPC transport in addition to HTTP Gateway
- Better TTS providers such as OpenAI or ElevenLabs
- Faster-whisper or another pluggable STT backend
- Streaming STT and streaming assistant responses
- Tray icon and background operation
- Conversation history persistence
- Configurable hotkeys
- Installer/package build for Windows
