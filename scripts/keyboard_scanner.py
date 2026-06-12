#!/usr/bin/env python3
"""Keyboard controller for the shared scanner state file."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

try:
    from scanner_state import DEFAULT_STATE_PATH, read_state, write_state
    from scanner_statectl import COMMANDS, apply_command, load_locations
except ImportError:  # pragma: no cover - used when imported as scripts.keyboard_scanner
    from scripts.scanner_state import DEFAULT_STATE_PATH, read_state, write_state
    from scripts.scanner_statectl import COMMANDS, apply_command, load_locations


def apply_keyboard_command(path: str | Path, command: str, locations: list[dict[str, Any]]) -> str | None:
    command = command.strip()
    if command not in COMMANDS or command in {"?", "q"}:
        return None
    state = apply_command(read_state(path), command, locations)
    write_state(path, state)
    return state.status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update scanner mode, quantity, and location from a keyboard.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH), help="State JSON file read by device_scanner.py")
    parser.add_argument("--server", help="Optional Grocy Ultimate Lookup base URL for location cycling")
    return parser.parse_args()


def print_help() -> None:
    print("Commands: a=add, r=remove, s=set, +=qty up, -=qty down, l=next location, ?=status, q=quit")
    print("Barcode scans are handled by device_scanner.py; this process only writes the shared state file.")


def main() -> int:
    args = parse_args()
    locations = load_locations(args.server)
    state = read_state(args.state_file)
    write_state(args.state_file, state)

    print_help()
    print(f"Ready: {state.status()}")
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            if line == "q":
                return 0
            if line == "?":
                print(f"Ready: {read_state(args.state_file).status()}")
                continue
            status = apply_keyboard_command(args.state_file, line, locations)
            if status is None:
                print("Unknown command. Scan barcodes in the device_scanner.py process.")
                continue
            print(f"Ready: {status}")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
