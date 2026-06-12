#!/usr/bin/env python3
"""Map GPIO button presses to the shared scanner state file."""

from __future__ import annotations

import argparse
import json
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scanner_state import DEFAULT_STATE_PATH, FileScannerState, normalize_state, read_state, write_state
    from scanner_statectl import apply_command, load_locations
except ImportError:  # pragma: no cover - used when imported as scripts.gpio_state_controller
    from scripts.scanner_state import DEFAULT_STATE_PATH, FileScannerState, normalize_state, read_state, write_state
    from scripts.scanner_statectl import apply_command, load_locations


DEFAULT_CONFIG_PATH = Path("scanner-buttons.json")
VALID_ACTIONS = {"mode", "quantity_delta", "quantity_set", "location_next"}


@dataclass(frozen=True)
class Control:
    pin: int | None
    action: str
    value: str | int | float | None = None
    key: str | None = None
    esp32_pin: int | None = None
    pull_up: bool = True
    bounce_time: float = 0.05


@dataclass(frozen=True)
class ControllerConfig:
    state_file: Path
    controls: dict[str, Control]
    device_id: str | None = None
    server_url: str | None = None
    scanner_type: str | None = None
    scanner_submit_suffix: str | None = None
    display_type: str | None = None


def load_config(path: str | Path) -> ControllerConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw_device = raw.get("device") if isinstance(raw.get("device"), dict) else {}
    raw_scanner = raw.get("scanner") if isinstance(raw.get("scanner"), dict) else {}
    raw_display = raw.get("display") if isinstance(raw.get("display"), dict) else {}
    state_file = Path(raw.get("state_file") or DEFAULT_STATE_PATH)
    raw_controls = raw.get("controls") or {}
    controls: dict[str, Control] = {}
    for name, control in raw_controls.items():
        if not isinstance(control, dict):
            raise ValueError(f"Control {name!r} must be an object")
        action = str(control.get("action") or "")
        if action not in VALID_ACTIONS:
            raise ValueError(f"Control {name!r} has unsupported action {action!r}")
        pin = control.get("pin")
        esp32_pin = control.get("esp32_pin")
        controls[str(name)] = Control(
            pin=int(pin) if pin not in (None, "") else None,
            action=action,
            value=control.get("value"),
            key=str(control["key"]) if control.get("key") not in (None, "") else None,
            esp32_pin=int(esp32_pin) if esp32_pin not in (None, "") else None,
            pull_up=bool(control.get("pull_up", True)),
            bounce_time=float(control.get("bounce_time", 0.05)),
        )
    if not controls:
        raise ValueError("Config must define at least one control")
    return ControllerConfig(
        state_file=state_file,
        controls=controls,
        device_id=str(raw_device["id"]) if raw_device.get("id") not in (None, "") else None,
        server_url=str(raw_device["server_url"]) if raw_device.get("server_url") not in (None, "") else None,
        scanner_type=str(raw_scanner["type"]) if raw_scanner.get("type") not in (None, "") else None,
        scanner_submit_suffix=(
            str(raw_scanner["submit_suffix"]) if raw_scanner.get("submit_suffix") not in (None, "") else None
        ),
        display_type=str(raw_display["type"]) if raw_display.get("type") not in (None, "") else None,
    )


def apply_control(
    state_file: str | Path,
    action: str,
    value: str | int | float | None,
    locations: list[dict[str, Any]],
) -> str:
    state = read_state(state_file)
    if action == "mode":
        state = normalize_state({**state.as_json(), "mode": value})
    elif action == "quantity_delta":
        state = normalize_state({**state.as_json(), "quantity": state.quantity + float(value or 0)})
    elif action == "quantity_set":
        state = normalize_state({**state.as_json(), "quantity": float(value or 0)})
    elif action == "location_next":
        state = apply_command(state, "l", locations)
    else:
        raise ValueError(f"Unsupported action {action!r}")
    write_state(state_file, state)
    return state.status()


def apply_named_control(
    config: ControllerConfig,
    control_name: str,
    locations: list[dict[str, Any]],
) -> str | None:
    control = config.controls.get(control_name)
    if control is None:
        for name, candidate in config.controls.items():
            if candidate.key == control_name:
                control = candidate
                break
    if control is None:
        return None
    return apply_control(config.state_file, control.action, control.value, locations)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update scanner state from configurable GPIO buttons.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Button mapping JSON config")
    parser.add_argument("--server", help="Optional Grocy Ultimate Lookup base URL for location cycling")
    parser.add_argument("--stdin", action="store_true", help="Read control names or keys from stdin instead of GPIO")
    parser.add_argument("--show", action="store_true", help="Print configured controls and exit")
    return parser.parse_args()


def print_controls(config: ControllerConfig) -> None:
    if config.device_id:
        print(f"Device: {config.device_id}")
    if config.server_url:
        print(f"Server: {config.server_url}")
    if config.scanner_type:
        print(f"Scanner: {config.scanner_type}")
    if config.display_type:
        print(f"Display: {config.display_type}")
    print(f"State file: {config.state_file}")
    for name, control in config.controls.items():
        pin = f"pin {control.pin}" if control.pin is not None else "no pi pin"
        esp32_pin = f", esp32 pin {control.esp32_pin}" if control.esp32_pin is not None else ""
        key = f", key {control.key}" if control.key else ""
        value = f" {control.value}" if control.value is not None else ""
        print(f"- {name}: {pin}{esp32_pin}{key}, {control.action}{value}")


def run_stdin(config: ControllerConfig, locations: list[dict[str, Any]]) -> int:
    write_state(config.state_file, read_state(config.state_file))
    print_controls(config)
    print(f"Ready: {read_state(config.state_file).status()}")
    try:
        while True:
            control_name = input("> ").strip()
            if control_name in {"q", "quit", "exit"}:
                return 0
            if not control_name:
                continue
            status = apply_named_control(config, control_name, locations)
            if status is None:
                print("Unknown control")
                continue
            print(f"Ready: {status}")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def run_gpio(config: ControllerConfig, locations: list[dict[str, Any]]) -> int:
    try:
        from gpiozero import Button
    except ImportError as exc:  # pragma: no cover - requires Pi dependencies
        raise RuntimeError("Install gpiozero on the Raspberry Pi, or run with --stdin for testing") from exc

    buttons = []

    def handler(name: str) -> None:
        status = apply_named_control(config, name, locations)
        if status:
            print(f"Ready: {status}", flush=True)

    for name, control in config.controls.items():
        if control.pin is None:
            continue
        button = Button(control.pin, pull_up=control.pull_up, bounce_time=control.bounce_time)
        button.when_pressed = lambda control_name=name: handler(control_name)
        buttons.append(button)
    if not buttons:
        raise RuntimeError("GPIO mode needs at least one control with a pin")

    write_state(config.state_file, read_state(config.state_file))
    print_controls(config)
    print(f"Ready: {read_state(config.state_file).status()}")
    signal.pause()
    return 0


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    locations = load_locations(args.server)
    if args.show:
        print_controls(config)
        return 0
    if args.stdin:
        return run_stdin(config, locations)
    return run_gpio(config, locations)


if __name__ == "__main__":
    raise SystemExit(main())
