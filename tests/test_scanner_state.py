from pathlib import Path

from scripts.scanner_state import FileScannerState, normalize_state, payload_from_state, read_state, write_state
from scripts.scanner_statectl import apply_command


def test_read_state_returns_defaults_when_file_is_missing(tmp_path: Path) -> None:
    state = read_state(tmp_path / "missing.json")

    assert state == FileScannerState(mode="add", quantity=1, location_id=None, location_name=None)
    assert state.status() == "ADD x1 @ Product default"


def test_state_file_round_trip_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "scanner-state.json"
    write_state(path, FileScannerState(mode="remove", quantity=2, location_id=7, location_name="Fridge"))

    state = read_state(path)

    assert state.status() == "REMOVE x2 @ Fridge"
    assert payload_from_state("kitchen-pi", " 066200032500 ", state) == {
        "device_id": "kitchen-pi",
        "barcode": "066200032500",
        "mode": "remove",
        "quantity": 2,
        "location_id": 7,
    }


def test_normalize_state_prevents_invalid_mode_and_quantity() -> None:
    assert normalize_state({"mode": "bad", "quantity": -10}).as_json() == {
        "mode": "add",
        "quantity": 1,
        "location_id": None,
        "location_name": None,
    }
    assert normalize_state({"mode": "set", "quantity": -10}).quantity == 0


def test_state_control_commands_update_quantity_mode_and_location() -> None:
    locations = [{"id": 2, "name": "Fridge"}, {"id": 3, "name": "Pantry"}]
    state = FileScannerState(location_id=2, location_name="Fridge")

    state = apply_command(state, "r", locations)
    state = apply_command(state, "+", locations)
    state = apply_command(state, "l", locations)
    state = apply_command(state, "s", locations)
    state = apply_command(state, "-", locations)
    state = apply_command(state, "-", locations)

    assert state == FileScannerState(mode="set", quantity=0, location_id=3, location_name="Pantry")
