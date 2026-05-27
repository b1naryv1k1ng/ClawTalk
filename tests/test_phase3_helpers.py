import unittest
from pathlib import Path

from clawtalk.hotkey import GlobalHotkeyManager, HotkeyError, parse_hotkey
from clawtalk.recorder import (
    AudioDeviceInfo,
    AudioRecorder,
    RecordingResult,
    RecordingStats,
    analyze_audio_levels,
    build_recording_file_path,
    format_audio_device,
    format_file_size,
    format_recording_result,
)


class FakeAudioRecorder(AudioRecorder):
    def __init__(self, sample_rate: int, fail_all: bool = False) -> None:
        super().__init__(sample_rate=sample_rate)
        self.checked_rates = []
        self.fail_all = fail_all

    def _get_sounddevice_module(self):
        return object()

    def _check_input_settings(self, sounddevice_module, device_index: int, sample_rate: int) -> None:
        self.checked_rates.append(sample_rate)
        if self.fail_all or sample_rate == 16000:
            raise RuntimeError("Invalid sample rate")


class Phase3HelpersTests(unittest.TestCase):
    def test_parse_hotkey_accepts_ctrl_shift_f9(self) -> None:
        binding = parse_hotkey("ctrl+shift+f9")
        self.assertEqual(binding.modifiers, frozenset({"ctrl", "shift"}))
        self.assertEqual(binding.trigger, "f9")

    def test_parse_hotkey_rejects_unsupported_trigger(self) -> None:
        with self.assertRaises(HotkeyError):
            parse_hotkey("ctrl+r")

    def test_format_file_size_kilobytes(self) -> None:
        self.assertEqual(format_file_size(2048), "2.0 KB")

    def test_format_recording_result(self) -> None:
        result = RecordingResult(
            file_path=Path("C:/tmp/test.wav"),
            duration_seconds=1.25,
            file_size_bytes=4096,
            device_index=3,
            device_name="USB Mic",
            stats=RecordingStats(peak_amplitude=2000, rms_level=400, appears_silent=False),
        )
        summary = format_recording_result(result)
        self.assertIn(str(result.file_path), summary)
        self.assertIn("duration=1.25s", summary)
        self.assertIn("size=4.0 KB", summary)
        self.assertIn("input=USB Mic", summary)
        self.assertIn("peak=2000", summary)
        self.assertIn("rms=400", summary)

    def test_build_recording_file_path_is_unique_with_same_timestamp(self) -> None:
        directory = Path("C:/tmp")
        first = build_recording_file_path(directory, 1000.0)
        second = build_recording_file_path(directory, 1000.0)

        self.assertNotEqual(first, second)
        self.assertTrue(first.name.endswith(".wav"))
        self.assertTrue(second.name.endswith(".wav"))

    def test_analyze_audio_levels_detects_silence(self) -> None:
        stats = analyze_audio_levels(b"\x00\x00" * 10)
        self.assertTrue(stats.appears_silent)
        self.assertEqual(stats.peak_amplitude, 0)
        self.assertEqual(stats.rms_level, 0)

    def test_analyze_audio_levels_detects_signal(self) -> None:
        stats = analyze_audio_levels(b"\x10\x00\x20\x00" * 10)
        self.assertFalse(stats.appears_silent)
        self.assertGreater(stats.peak_amplitude, 0)
        self.assertGreater(stats.rms_level, 0)

    def test_format_audio_device(self) -> None:
        device = AudioDeviceInfo(
            index=4,
            name="Logitech Headset Mic",
            max_input_channels=1,
            default_sample_rate=48000.0,
            is_default_input=True,
        )
        formatted = format_audio_device(device)
        self.assertIn("[4]", formatted)
        self.assertIn("Logitech Headset Mic", formatted)
        self.assertIn("[default]", formatted)

    def test_resolve_input_sample_rate_falls_back_to_device_default(self) -> None:
        device = AudioDeviceInfo(
            index=33,
            name="Logitech Headset Mic",
            max_input_channels=1,
            default_sample_rate=48000.0,
            is_default_input=False,
        )
        recorder = FakeAudioRecorder(sample_rate=16000)
        sample_rate = recorder._resolve_input_sample_rate(device)
        self.assertEqual(sample_rate, 48000)
        self.assertEqual(recorder.checked_rates, [16000, 48000])

    def test_resolve_input_sample_rate_raises_when_requested_and_fallback_fail(self) -> None:
        device = AudioDeviceInfo(
            index=33,
            name="Logitech Headset Mic",
            max_input_channels=1,
            default_sample_rate=48000.0,
            is_default_input=False,
        )
        recorder = FakeAudioRecorder(sample_rate=16000, fail_all=True)
        with self.assertRaises(Exception):
            recorder._resolve_input_sample_rate(device)

    def test_hotkey_press_repeated_press_release_is_single_cycle(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, ["start"])
        self.assertEqual(stops, ["stop"])

    def test_hotkey_f9_press_release_alone_does_not_start_or_stop(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")

        self.assertEqual(starts, [])
        self.assertEqual(stops, [])

    def test_hotkey_ctrl_press_release_alone_does_not_start_or_stop(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, [])
        self.assertEqual(stops, [])

    def test_hotkey_press_release_press_release_is_two_cycles(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")
        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, ["start", "start"])
        self.assertEqual(stops, ["stop", "stop"])

    def test_hotkey_releasing_ctrl_after_valid_combo_does_not_duplicate_stop(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, ["start"])
        self.assertEqual(stops, ["stop"])

    def test_hotkey_releasing_ctrl_first_after_valid_combo_stops_once(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.ctrl_l")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")

        self.assertEqual(starts, ["start"])
        self.assertEqual(stops, ["stop"])

    def test_hotkey_start_failure_suppresses_repeats_until_release(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager.notify_recording_start_failed()
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")
        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, ["start", "start"])
        self.assertEqual(stops, ["stop"])

    def test_hotkey_stop_failure_resets_for_next_cycle(self) -> None:
        starts = []
        stops = []
        manager = GlobalHotkeyManager(
            hotkey="ctrl+shift+f9",
            on_press_start=lambda: starts.append("start"),
            on_release_stop=lambda: stops.append("stop"),
        )

        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager.notify_recording_stop_failed()
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")
        manager._handle_press("Key.ctrl_l")
        manager._handle_press("Key.shift_l")
        manager._handle_press("Key.f9")
        manager._handle_release("Key.f9")
        manager._handle_release("Key.shift_l")
        manager._handle_release("Key.ctrl_l")

        self.assertEqual(starts, ["start", "start"])
        self.assertEqual(stops, ["stop"])


if __name__ == "__main__":
    unittest.main()
