from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import settings
from app.models import DeviceHeartbeatRequest, DeviceStatus


@dataclass
class ScannerDeviceRecord:
    device_id: str
    last_seen: datetime
    mode: str | None = None
    quantity: float | None = None
    location_id: int | None = None
    location_name: str | None = None
    version: str | None = None


class ScannerDeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, ScannerDeviceRecord] = {}

    def heartbeat(self, request: DeviceHeartbeatRequest) -> DeviceStatus:
        record = ScannerDeviceRecord(
            device_id=request.device_id,
            last_seen=datetime.now(UTC),
            mode=request.mode,
            quantity=request.quantity,
            location_id=request.location_id,
            location_name=request.location_name,
            version=request.version,
        )
        self._devices[request.device_id] = record
        return self._status(record)

    def list(self) -> list[DeviceStatus]:
        return [self._status(record) for record in sorted(self._devices.values(), key=lambda item: item.device_id)]

    def _status(self, record: ScannerDeviceRecord) -> DeviceStatus:
        age = (datetime.now(UTC) - record.last_seen).total_seconds()
        return DeviceStatus(
            device_id=record.device_id,
            online=age <= settings.scanner_device_offline_after_seconds,
            last_seen=record.last_seen.isoformat(),
            mode=record.mode,
            quantity=record.quantity,
            location_id=record.location_id,
            location_name=record.location_name,
            version=record.version,
        )


def parse_device_tokens(value: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        device_id, token = item.split(":", 1)
        device_id = device_id.strip()
        token = token.strip()
        if device_id and token:
            tokens[device_id] = token
    return tokens


def expected_device_token(device_id: str) -> str | None:
    return parse_device_tokens(settings.scanner_device_tokens).get(device_id)
