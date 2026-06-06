from scripts.keyboard_scanner import ScannerState


def test_keyboard_state_changes_mode_quantity_and_location() -> None:
    state = ScannerState(locations=[{"id": 2, "name": "Fridge"}, {"id": 3, "name": "Pantry"}])

    assert state.mode == "add"
    assert state.quantity == 1
    assert state.location_id == 2

    assert state.apply_command("r") == "mode=remove"
    assert state.apply_command("+") == "quantity=2"
    assert state.apply_command("l") == "location=Pantry"
    assert state.apply_command("s") == "mode=set"
    assert state.apply_command("-") == "quantity=1"
    assert state.apply_command("-") == "quantity=0"

    assert state.mode == "set"
    assert state.quantity == 0
    assert state.location_id == 3


def test_keyboard_state_prevents_zero_quantity_for_add_and_remove() -> None:
    state = ScannerState(locations=[])
    state.apply_command("s")
    state.apply_command("-")

    assert state.quantity == 0

    state.apply_command("a")

    assert state.mode == "add"
    assert state.quantity == 1


def test_keyboard_state_builds_scan_payload() -> None:
    state = ScannerState(locations=[{"id": 2, "name": "Fridge"}], device_id="test-pi")
    state.apply_command("+")

    assert state.payload("012345") == {
        "device_id": "test-pi",
        "barcode": "012345",
        "mode": "add",
        "quantity": 2,
        "location_id": 2,
    }
