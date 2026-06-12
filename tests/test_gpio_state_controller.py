from pathlib import Path

from scripts.gpio_state_controller import apply_control, load_config
from scripts.scanner_state import FileScannerState, read_state, write_state


def test_load_config_defaults_to_shared_state_file(tmp_path: Path) -> None:
    config_path = tmp_path / "buttons.json"
    config_path.write_text(
        """
        {
          "controls": {
            "add": { "pin": 5, "action": "mode", "value": "add" }
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert str(config.state_file).endswith("state.json")
    assert config.controls["add"].pin == 5
    assert config.controls["add"].action == "mode"
    assert config.controls["add"].value == "add"


def test_load_config_preserves_cross_target_device_and_scanner_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "buttons.json"
    config_path.write_text(
        """
        {
          "device": {
            "id": "kitchen-scanner",
            "server_url": "http://grocy.local:9290"
          },
          "scanner": {
            "type": "usb_hid",
            "submit_suffix": "enter"
          },
          "display": {
            "type": "text",
            "status_template": "{mode} x{quantity} @ {location}"
          },
          "controls": {
            "add": { "pin": 5, "esp32_pin": 4, "key": "a", "action": "mode", "value": "add" }
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.device_id == "kitchen-scanner"
    assert config.server_url == "http://grocy.local:9290"
    assert config.scanner_type == "usb_hid"
    assert config.scanner_submit_suffix == "enter"
    assert config.display_type == "text"
    assert config.controls["add"].pin == 5
    assert config.controls["add"].esp32_pin == 4


def test_apply_control_updates_mode_quantity_and_location(tmp_path: Path) -> None:
    state_file = tmp_path / "scanner-state.json"
    write_state(state_file, FileScannerState(location_id=2, location_name="Fridge"))
    locations = [{"id": 2, "name": "Fridge"}, {"id": 3, "name": "Pantry"}]

    assert apply_control(state_file, "mode", "remove", locations) == "REMOVE x1 @ Fridge"
    assert apply_control(state_file, "quantity_delta", 1, locations) == "REMOVE x2 @ Fridge"
    assert apply_control(state_file, "location_next", None, locations) == "REMOVE x2 @ Pantry"
    assert read_state(state_file) == FileScannerState(
        mode="remove",
        quantity=2,
        location_id=3,
        location_name="Pantry",
    )


def test_apply_control_supports_quantity_zero_for_set_mode(tmp_path: Path) -> None:
    state_file = tmp_path / "scanner-state.json"
    write_state(state_file, FileScannerState(mode="set", quantity=3))

    assert apply_control(state_file, "quantity_set", 0, []) == "SET x0 @ Product default"
    assert read_state(state_file).quantity == 0
