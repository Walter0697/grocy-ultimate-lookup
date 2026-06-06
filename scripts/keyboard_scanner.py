#!/usr/bin/env python3
"""Keyboard-button simulator for the future Raspberry Pi scanner controls."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


COMMANDS = {"a", "r", "s", "+", "-", "l", "?", "q"}


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class ScannerState:
    locations: list[dict[str, Any]]
    device_id: str = "keyboard-pi"
    mode: str = "add"
    quantity: float = 1
    location_index: int = 0
    messages: list[str] = field(default_factory=list)

    @property
    def location_id(self) -> int | None:
        if not self.locations:
            return None
        return int(self.locations[self.location_index]["id"])

    @property
    def location_name(self) -> str:
        if not self.locations:
            return "Product default"
        return str(self.locations[self.location_index]["name"])

    def apply_command(self, command: str) -> str:
        if command == "a":
            self.mode = "add"
            self.quantity = max(self.quantity, 1)
            return "mode=add"
        if command == "r":
            self.mode = "remove"
            self.quantity = max(self.quantity, 1)
            return "mode=remove"
        if command == "s":
            self.mode = "set"
            return "mode=set"
        if command == "+":
            self.quantity += 1
            return f"quantity={self._display_quantity()}"
        if command == "-":
            minimum = 0 if self.mode == "set" else 1
            self.quantity = max(minimum, self.quantity - 1)
            return f"quantity={self._display_quantity()}"
        if command == "l":
            if not self.locations:
                return "location=Product default"
            self.location_index = (self.location_index + 1) % len(self.locations)
            return f"location={self.location_name}"
        if command == "?":
            return self.status()
        return "unknown command"

    def payload(self, barcode: str) -> dict[str, Any]:
        data = {
            "device_id": self.device_id,
            "barcode": barcode.strip(),
            "mode": self.mode,
            "quantity": self.quantity,
        }
        if self.location_id is not None:
            data["location_id"] = self.location_id
        return data

    def status(self) -> str:
        return f"{self.mode.upper()} x{self._display_quantity()} @ {self.location_name}"

    def _display_quantity(self) -> str:
        return str(int(self.quantity)) if self.quantity == int(self.quantity) else str(self.quantity)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate Pi scanner buttons from a keyboard.")
    parser.add_argument("--server", default="http://localhost:9290", help="Grocy Ultimate Lookup base URL")
    parser.add_argument("--device-id", default="keyboard-pi", help="Device ID shown in the dashboard")
    parser.add_argument("--location-id", type=int, help="Initial Grocy location ID")
    return parser.parse_args()


def load_locations(server: str) -> list[dict[str, Any]]:
    options = get_json(f"{server.rstrip('/')}/dashboard/options")
    return options.get("locations", [])


def choose_initial_location(locations: list[dict[str, Any]], location_id: int | None) -> int:
    if location_id is None:
        return 0
    for index, location in enumerate(locations):
        if int(location["id"]) == location_id:
            return index
    return 0


def print_help() -> None:
    print("Commands: a=add, r=remove, s=set, +=qty up, -=qty down, l=next location, ?=status, q=quit")
    print("Any other line is treated as a barcode and submitted with the current state.")


def print_result(result: dict[str, Any]) -> None:
    marker = "REVIEW" if result.get("needs_review") else "OK"
    print(f"[{marker}] {result.get('message')}")


def main() -> int:
    args = parse_args()
    server = args.server.rstrip("/")
    locations = load_locations(server)
    state = ScannerState(locations=locations, device_id=args.device_id)
    state.location_index = choose_initial_location(locations, args.location_id)

    print_help()
    print(f"Ready: {state.status()}")
    failures = 0
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            if line in COMMANDS:
                if line == "q":
                    break
                print(state.apply_command(line))
                print(f"Ready: {state.status()}")
                continue
            try:
                print(f"Scanning {line} with {state.status()}")
                print_result(post_json(f"{server}/scanner/scan", state.payload(line)))
            except urllib.error.HTTPError as exc:
                failures += 1
                print(exc.read().decode("utf-8"), file=sys.stderr)
            except Exception as exc:
                failures += 1
                print(f"Scan failed: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
