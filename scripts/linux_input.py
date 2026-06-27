#!/usr/bin/env python3
"""Linux input-device discovery and barcode scanner helpers."""

from __future__ import annotations

import errno
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


EV_KEY = 0x01
KEY_ENTER = 28
KEY_KPENTER = 96
INPUT_EVENT = struct.Struct("llHHI")

KEYCODE_MAP = {
    2: "1",
    3: "2",
    4: "3",
    5: "4",
    6: "5",
    7: "6",
    8: "7",
    9: "8",
    10: "9",
    11: "0",
    12: "-",
    52: ".",
    79: "1",
    80: "2",
    81: "3",
    75: "4",
    76: "5",
    77: "6",
    71: "7",
    72: "8",
    73: "9",
    82: "0",
}

SCANNER_NAME_HINTS = (
    "scanner",
    "barcode",
    "honeywell",
    "zebra",
    "datalogic",
    "symbol",
    "socket mobile",
)
GENERIC_KEYBOARD_HINTS = (
    "keyboard",
    "at translated",
    "apple internal",
)


@dataclass(frozen=True)
class InputDeviceCandidate:
    event_path: str
    stable_path: str
    name: str
    vendor_id: str
    product_id: str
    score: int
    reasons: list[str]

    @property
    def preferred_path(self) -> str:
        return self.stable_path or self.event_path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _stable_paths(dev_root: Path) -> dict[str, str]:
    by_id_root = dev_root / "by-id"
    if not by_id_root.exists():
        return {}
    mapping: dict[str, str] = {}
    for path in sorted(by_id_root.iterdir()):
        try:
            resolved = str(path.resolve(strict=True))
        except OSError:
            continue
        mapping.setdefault(resolved, str(path))
    return mapping


def _candidate_score(name: str, stable_path: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    lowered_name = name.lower()
    lowered_path = stable_path.lower()
    lowered_basename = Path(stable_path).name.lower()
    if "/by-id/" in lowered_path:
        score += 2
        reasons.append("stable-path:by-id")
    if lowered_path.endswith("-event-kbd"):
        score += 2
        reasons.append("stable-path:event-kbd")
    for hint in SCANNER_NAME_HINTS:
        if hint in lowered_name or hint in lowered_basename:
            score += 4
            reasons.append(f"name:{hint}")
            break
    for hint in GENERIC_KEYBOARD_HINTS:
        if hint in lowered_name:
            score -= 4
            reasons.append(f"name:{hint}")
            break
    return score, reasons


def discover_input_devices(
    dev_root: str | Path = "/dev/input",
    sys_root: str | Path = "/sys/class/input",
) -> list[InputDeviceCandidate]:
    dev_root = Path(dev_root)
    sys_root = Path(sys_root)
    stable_paths = _stable_paths(dev_root)
    devices: list[InputDeviceCandidate] = []
    for event_path in sorted(dev_root.glob("event*")):
        event_name = event_path.name
        event_root = sys_root / event_name
        if not event_root.exists():
            continue
        name = _read_text(event_root / "device" / "name")
        vendor_id = _read_text(event_root / "device" / "id" / "vendor")
        product_id = _read_text(event_root / "device" / "id" / "product")
        stable_path = stable_paths.get(str(event_path.resolve()), str(event_path))
        score, reasons = _candidate_score(name, stable_path)
        devices.append(
            InputDeviceCandidate(
                event_path=str(event_path),
                stable_path=stable_path,
                name=name or event_name,
                vendor_id=vendor_id,
                product_id=product_id,
                score=score,
                reasons=reasons,
            )
        )
    devices.sort(key=lambda item: (-item.score, item.name, item.event_path))
    return devices


def detect_scanner_candidate(
    dev_root: str | Path = "/dev/input",
    sys_root: str | Path = "/sys/class/input",
) -> InputDeviceCandidate | None:
    devices = discover_input_devices(dev_root=dev_root, sys_root=sys_root)
    if not devices:
        return None
    top = devices[0]
    return top if top.score >= 4 else None


def decode_key_event(code: int) -> str | None:
    if code in {KEY_ENTER, KEY_KPENTER}:
        return "\n"
    return KEYCODE_MAP.get(code)


def iter_barcode_scans(device_path: str | Path) -> Iterator[str]:
    buffer: list[str] = []
    with Path(device_path).open("rb", buffering=0) as handle:
        while True:
            chunk = handle.read(INPUT_EVENT.size)
            if not chunk:
                break
            if len(chunk) != INPUT_EVENT.size:
                continue
            _, _, event_type, code, value = INPUT_EVENT.unpack(chunk)
            if event_type != EV_KEY or value != 1:
                continue
            decoded = decode_key_event(code)
            if decoded is None:
                continue
            if decoded == "\n":
                barcode = "".join(buffer).strip()
                buffer.clear()
                if barcode:
                    yield barcode
                continue
            buffer.append(decoded)


def is_linux_input_device(path: str | Path) -> bool:
    return Path(path).exists()


def open_device_error_message(path: str | Path, exc: OSError) -> str:
    if exc.errno == errno.EACCES:
        return f"Permission denied opening scanner device {path}. Run the service with access to /dev/input."
    if exc.errno == errno.ENOENT:
        return f"Scanner device {path} was not found."
    return f"Unable to open scanner device {path}: {exc}"
