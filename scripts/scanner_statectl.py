#!/usr/bin/env python3
"""Update the scanner state file from a keyboard or shell command."""

from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import replace
from typing import Any

try:
    from scanner_state import DEFAULT_STATE_PATH, FileScannerState, normalize_state, read_state, write_state
except ImportError:  # pragma: no cover - used when imported as scripts.scanner_statectl
    from scripts.scanner_state import DEFAULT_STATE_PATH, FileScannerState, normalize_state, read_state, write_state


COMMANDS = {"a", "r", "s", "+", "-", "l", "?", "q"}


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def load_locations(server: str | None) -> list[dict[str, Any]]:
    if not server:
        return []
    try:
        options = get_json(f"{server.rstrip('/')}/dashboard/options")
    except Exception:
        return []
    return options.get("locations", [])


def location_index(locations: list[dict[str, Any]], location_id: int | None) -> int:
    for index, location in enumerate(locations):
        if int(location["id"]) == location_id:
            return index
    return 0


def apply_command(state: FileScannerState, command: str, locations: list[dict[str, Any]]) -> FileScannerState:
    if command == "a":
        return replace(state, mode="add", quantity=max(state.quantity, 1))
    if command == "r":
        return replace(state, mode="remove", quantity=max(state.quantity, 1))
    if command == "s":
        return replace(state, mode="set")
    if command == "+":
        return replace(state, quantity=state.quantity + 1)
    if command == "-":
        minimum = 0 if state.mode == "set" else 1
        return replace(state, quantity=max(minimum, state.quantity - 1))
    if command == "l":
        if not locations:
            return replace(state, location_id=None, location_name=None)
        next_index = (location_index(locations, state.location_id) + 1) % len(locations)
        location = locations[next_index]
        return replace(state, location_id=int(location["id"]), location_name=str(location["name"]))
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read or update the scanner state JSON file.")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH), help="State JSON file path")
    parser.add_argument("--server", help="Optional Grocy Ultimate Lookup base URL for location cycling")
    parser.add_argument("--mode", choices=["add", "remove", "set"], help="Set scanner mode")
    parser.add_argument("--quantity", type=float, help="Set scanner quantity")
    parser.add_argument("--location-id", type=int, help="Set Grocy location ID")
    parser.add_argument("--location-name", help="Set display name for the current location")
    parser.add_argument("--show", action="store_true", help="Print the current state and exit")
    parser.add_argument("--interactive", action="store_true", help="Run keyboard control loop")
    return parser.parse_args()


def apply_arg_updates(state: FileScannerState, args: argparse.Namespace) -> FileScannerState:
    updates: dict[str, Any] = {}
    if args.mode:
        updates["mode"] = args.mode
    if args.quantity is not None:
        updates["quantity"] = args.quantity
    if args.location_id is not None:
        updates["location_id"] = args.location_id
    if args.location_name is not None:
        updates["location_name"] = args.location_name
    if not updates:
        return state
    return normalize_state(replace(state, **updates).as_json())


def print_help() -> None:
    print("Commands: a=add, r=remove, s=set, +=qty up, -=qty down, l=next location, ?=status, q=quit")
    print("This process only writes the state file. The scanner process reads it before each barcode.")


def run_interactive(args: argparse.Namespace) -> int:
    locations = load_locations(args.server)
    state = read_state(args.state_file)
    write_state(args.state_file, state)

    print_help()
    print(f"Ready: {state.status()}")
    try:
        while True:
            command = input("> ").strip()
            if not command:
                continue
            if command == "q":
                return 0
            if command == "?":
                print(f"Ready: {state.status()}")
                continue
            if command not in COMMANDS:
                print("Unknown command. Use ? for status.")
                continue
            state = apply_command(state, command, locations)
            write_state(args.state_file, state)
            print(f"Ready: {state.status()}")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def main() -> int:
    args = parse_args()
    if args.interactive:
        return run_interactive(args)

    state = apply_arg_updates(read_state(args.state_file), args)
    write_state(args.state_file, state)
    print(state.status())
    if args.show:
        print(json.dumps(state.as_json(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
