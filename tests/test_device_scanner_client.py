from argparse import Namespace
from pathlib import Path

from scripts.device_scanner import auth_headers, heartbeat_payload, payload
from scripts.scanner_state import FileScannerState, write_state


def test_auth_headers_include_scanner_token_when_configured() -> None:
    assert auth_headers("secret-token") == {"X-Scanner-Token": "secret-token"}
    assert auth_headers(None) == {}


def test_heartbeat_payload_uses_state_file_values(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    write_state(state_file, FileScannerState(mode="remove", quantity=2, location_id=3, location_name="Pantry"))
    args = Namespace(device_id="kitchen-pi", state_file=str(state_file), mode="add", quantity=1, location_id=None)

    assert heartbeat_payload(args) == {
        "device_id": "kitchen-pi",
        "mode": "remove",
        "quantity": 2,
        "location_id": 3,
        "location_name": "Pantry",
        "version": "device_scanner.py",
    }


def test_scan_payload_still_uses_state_file_values(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    write_state(state_file, FileScannerState(mode="set", quantity=0, location_id=4, location_name="Shelf"))
    args = Namespace(device_id="kitchen-pi", state_file=str(state_file), mode="add", quantity=1, location_id=None)

    assert payload(args, "123456") == {
        "device_id": "kitchen-pi",
        "barcode": "123456",
        "mode": "set",
        "quantity": 0,
        "location_id": 4,
    }
