from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Set


logger = logging.getLogger(__name__)


class HotkeyError(Exception):
    pass


@dataclass(frozen=True)
class HotkeyBinding:
    modifiers: frozenset[str]
    trigger: str


class GlobalHotkeyManager:
    def __init__(
        self,
        hotkey: str = "ctrl+space",
        on_press_start: Optional[Callable[[], None]] = None,
        on_release_stop: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._binding = parse_hotkey(hotkey)
        self._on_press_start = on_press_start
        self._on_release_stop = on_release_stop
        self._on_error = on_error
        self._listener = None
        self._pressed_modifiers: Set[str] = set()
        self._trigger_pressed = False
        self._combo_active = False
        self._suppress_until_release = False

    @property
    def hotkey_label(self) -> str:
        modifier_label = "+".join(sorted(self._binding.modifiers))
        return f"{modifier_label}+{self._binding.trigger}" if modifier_label else self._binding.trigger

    def start(self) -> None:
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise HotkeyError(
                "The 'pynput' package is not installed. Run pip install -r requirements.txt."
            ) from exc

        try:
            self._listener = keyboard.Listener(
                on_press=self._handle_press,
                on_release=self._handle_release,
            )
            self._listener.start()
            logger.info("Global hotkey started: %s", self.hotkey_label)
        except Exception as exc:
            raise HotkeyError(f"Could not register global hotkey: {exc}") from exc

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            self._pressed_modifiers.clear()
            self._trigger_pressed = False
            self._combo_active = False
            self._suppress_until_release = False
            logger.info("Global hotkey stopped.")

    def notify_recording_start_failed(self) -> None:
        logger.info(
            "Resetting hotkey state after recording start failure: %s",
            self.hotkey_label,
        )
        self._combo_active = False
        self._suppress_until_release = True

    def notify_recording_stop_failed(self) -> None:
        logger.info(
            "Resetting hotkey state after recording stop failure: %s",
            self.hotkey_label,
        )
        self._combo_active = False

    def _handle_press(self, key) -> None:  # type: ignore[no-untyped-def]
        try:
            normalized = normalize_pynput_key(key)
            if normalized in self._binding.modifiers:
                self._pressed_modifiers.add(normalized)
                return

            if normalized == self._binding.trigger:
                self._trigger_pressed = True
                if self._suppress_until_release:
                    logger.debug(
                        "Ignoring repeated hotkey press until release: %s",
                        self.hotkey_label,
                    )
                    return
                if not self._binding.modifiers.issubset(self._pressed_modifiers):
                    return
                if self._combo_active:
                    logger.debug(
                        "Ignoring repeated hotkey press while held: %s",
                        self.hotkey_label,
                    )
                    return

                self._combo_active = True
                logger.info("Global hotkey pressed: %s", self.hotkey_label)
                if self._on_press_start is not None:
                    self._on_press_start()
        except Exception as exc:  # pragma: no cover
            logger.exception("Hotkey press handling failed.")
            self._emit_error(f"Global hotkey handling failed: {exc}")

    def _handle_release(self, key) -> None:  # type: ignore[no-untyped-def]
        try:
            normalized = normalize_pynput_key(key)

            if normalized == self._binding.trigger:
                self._trigger_pressed = False
                if self._combo_active:
                    self._combo_active = False
                    logger.info("Global hotkey released: %s", self.hotkey_label)
                    if self._on_release_stop is not None:
                        self._on_release_stop()
                self._maybe_clear_suppression()
                return

            if normalized in self._binding.modifiers:
                modifier_was_pressed = normalized in self._pressed_modifiers
                self._pressed_modifiers.discard(normalized)
                if self._combo_active and modifier_was_pressed:
                    self._combo_active = False
                    logger.info("Global hotkey released: %s", self.hotkey_label)
                    if self._on_release_stop is not None:
                        self._on_release_stop()
                self._maybe_clear_suppression()
        except Exception as exc:  # pragma: no cover
            logger.exception("Hotkey release handling failed.")
            self._emit_error(f"Global hotkey handling failed: {exc}")

    def _emit_error(self, message: str) -> None:
        if self._on_error is not None:
            self._on_error(message)

    def _maybe_clear_suppression(self) -> None:
        if not self._pressed_modifiers and not self._trigger_pressed:
            self._suppress_until_release = False


def parse_hotkey(hotkey: str) -> HotkeyBinding:
    if not hotkey.strip():
        raise HotkeyError("Hotkey cannot be empty.")

    parts = [part.strip().lower() for part in hotkey.split("+") if part.strip()]
    if len(parts) < 2:
        raise HotkeyError("Hotkey must include at least one modifier and one key.")

    trigger = parts[-1]
    modifiers = frozenset(parts[:-1])
    supported_modifiers = {"ctrl", "shift", "alt"}
    if not modifiers.issubset(supported_modifiers):
        raise HotkeyError("Only ctrl, shift, and alt modifiers are supported.")
    if trigger != "space":
        raise HotkeyError("Only the space key is supported as the push-to-talk trigger.")

    return HotkeyBinding(modifiers=modifiers, trigger=trigger)


def normalize_pynput_key(key) -> str:  # type: ignore[no-untyped-def]
    if getattr(key, "char", None) == " ":
        return "space"

    key_string = str(key).lower()
    key_map = {
        "key.space": "space",
        "key.ctrl": "ctrl",
        "key.ctrl_l": "ctrl",
        "key.ctrl_r": "ctrl",
        "key.shift": "shift",
        "key.shift_l": "shift",
        "key.shift_r": "shift",
        "key.alt": "alt",
        "key.alt_l": "alt",
        "key.alt_r": "alt",
        "key.alt_gr": "alt",
    }
    return key_map.get(key_string, key_string)
