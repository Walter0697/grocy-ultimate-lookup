from pathlib import Path

from scripts.keyboard_scanner import apply_keyboard_command
from scripts.scanner_state import FileScannerState, read_state, write_state


def test_keyboard_command_updates_shared_state_file(tmp_path: Path) -> None:
    state_file = tmp_path / "scanner-state.json"
    write_state(state_file, FileScannerState(location_id=2, location_name="Fridge"))

    status = apply_keyboard_command(
        state_file,
        "l",
        [{"id": 2, "name": "Fridge"}, {"id": 3, "name": "Pantry"}],
    )

    assert status == "ADD x1 @ Pantry"
    assert read_state(state_file) == FileScannerState(
        mode="add",
        quantity=1,
        location_id=3,
        location_name="Pantry",
    )


def test_keyboard_command_uses_same_quantity_rules_as_hardware_controls(tmp_path: Path) -> None:
    state_file = tmp_path / "scanner-state.json"
    write_state(state_file, FileScannerState(mode="set", quantity=0))

    assert apply_keyboard_command(state_file, "a", []) == "ADD x1 @ Product default"
    assert read_state(state_file).quantity == 1


def test_keyboard_command_rejects_barcode_submission_lines(tmp_path: Path) -> None:
    state_file = tmp_path / "scanner-state.json"

    assert apply_keyboard_command(state_file, "012345", []) is None
    assert read_state(state_file) == FileScannerState()
