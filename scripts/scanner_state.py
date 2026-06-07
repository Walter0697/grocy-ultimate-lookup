"""Shared state-file helpers for hardware scanner clients."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path("/var/lib/grocy-scanner/state.json")
VALID_MODES = {"add", "remove", "set"}


@dataclass(frozen=True)
class FileScannerState:
    mode: str = "add"
    quantity: float = 1
    location_id: int | None = None
    location_name: str | None = None

    def display_quantity(self) -> str:
        return str(int(self.quantity)) if self.quantity == int(self.quantity) else str(self.quantity)

    def location_label(self) -> str:
        return self.location_name or "Product default"

    def status(self) -> str:
        return f"{self.mode.upper()} x{self.display_quantity()} @ {self.location_label()}"

    def as_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "mode": self.mode,
            "quantity": self.quantity,
            "location_id": self.location_id,
            "location_name": self.location_name,
        }
        return data


def normalize_state(raw: dict[str, Any] | None) -> FileScannerState:
    raw = raw or {}
    mode = str(raw.get("mode") or "add").lower()
    if mode not in VALID_MODES:
        mode = "add"

    try:
        quantity = float(raw.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1

    minimum = 0 if mode == "set" else 1
    quantity = max(minimum, quantity)

    location_id = raw.get("location_id")
    try:
        normalized_location_id = int(location_id) if location_id not in (None, "") else None
    except (TypeError, ValueError):
        normalized_location_id = None

    location_name = raw.get("location_name")
    normalized_location_name = str(location_name) if location_name not in (None, "") else None

    return FileScannerState(
        mode=mode,
        quantity=quantity,
        location_id=normalized_location_id,
        location_name=normalized_location_name,
    )


def read_state(path: str | Path | None = None) -> FileScannerState:
    state_path = Path(path) if path else DEFAULT_STATE_PATH
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return normalize_state(None)
    return normalize_state(raw if isinstance(raw, dict) else None)


def write_state(path: str | Path, state: FileScannerState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(state.as_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(state_path)


def payload_from_state(device_id: str, barcode: str, state: FileScannerState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": device_id,
        "barcode": barcode.strip(),
        "mode": state.mode,
        "quantity": state.quantity,
    }
    if state.location_id is not None:
        payload["location_id"] = state.location_id
    return payload
