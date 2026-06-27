from pathlib import Path

from scripts.linux_input import INPUT_EVENT, InputDeviceCandidate, detect_scanner_candidate, discover_input_devices, iter_barcode_scans


def _make_event(sys_root: Path, dev_root: Path, event_name: str, device_name: str, *, vendor: str, product: str) -> None:
    event_dir = sys_root / event_name
    device_dir = event_dir / "device"
    id_dir = device_dir / "id"
    id_dir.mkdir(parents=True, exist_ok=True)
    (device_dir / "name").write_text(device_name, encoding="utf-8")
    (id_dir / "vendor").write_text(vendor, encoding="utf-8")
    (id_dir / "product").write_text(product, encoding="utf-8")
    (dev_root / event_name).write_bytes(b"")


def test_discover_input_devices_prefers_by_id_stable_paths(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev" / "input"
    sys_root = tmp_path / "sys" / "class" / "input"
    by_id_root = dev_root / "by-id"
    by_id_root.mkdir(parents=True, exist_ok=True)
    _make_event(sys_root, dev_root, "event3", "Honeywell Xenon Scanner", vendor="0c2e", product="0b61")

    stable_link = by_id_root / "usb-Honeywell_Xenon-event-kbd"
    stable_link.symlink_to(dev_root / "event3")

    devices = discover_input_devices(dev_root=dev_root, sys_root=sys_root)

    assert devices == [
        InputDeviceCandidate(
            event_path=str(dev_root / "event3"),
            stable_path=str(stable_link),
                name="Honeywell Xenon Scanner",
                vendor_id="0c2e",
                product_id="0b61",
                score=8,
                reasons=["stable-path:by-id", "stable-path:event-kbd", "name:scanner"],
            )
        ]


def test_detect_scanner_candidate_prefers_scanner_like_name_over_generic_keyboard(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev" / "input"
    sys_root = tmp_path / "sys" / "class" / "input"
    by_id_root = dev_root / "by-id"
    by_id_root.mkdir(parents=True, exist_ok=True)

    _make_event(sys_root, dev_root, "event1", "Dell USB Keyboard", vendor="1234", product="0001")
    _make_event(sys_root, dev_root, "event2", "Datalogic USB Scanner", vendor="5678", product="0002")

    (by_id_root / "usb-dell-keyboard-event-kbd").symlink_to(dev_root / "event1")
    (by_id_root / "usb-datalogic-scanner-event-kbd").symlink_to(dev_root / "event2")

    detected = detect_scanner_candidate(dev_root=dev_root, sys_root=sys_root)

    assert detected is not None
    assert detected.name == "Datalogic USB Scanner"
    assert detected.event_path.endswith("event2")


def test_detect_scanner_candidate_returns_none_when_only_generic_keyboards_exist(tmp_path: Path) -> None:
    dev_root = tmp_path / "dev" / "input"
    sys_root = tmp_path / "sys" / "class" / "input"
    by_id_root = dev_root / "by-id"
    by_id_root.mkdir(parents=True, exist_ok=True)

    _make_event(sys_root, dev_root, "event1", "Dell USB Keyboard", vendor="1234", product="0001")
    _make_event(sys_root, dev_root, "event2", "AT Translated Set 2 keyboard", vendor="0001", product="0001")

    (by_id_root / "usb-dell-keyboard-event-kbd").symlink_to(dev_root / "event1")
    (by_id_root / "platform-i8042-serio-0-event-kbd").symlink_to(dev_root / "event2")

    assert detect_scanner_candidate(dev_root=dev_root, sys_root=sys_root) is None


def test_iter_barcode_scans_decodes_digit_keys_until_enter(tmp_path: Path) -> None:
    device_path = tmp_path / "event4"
    events = [
        INPUT_EVENT.pack(0, 0, 1, 11, 1),  # 0
        INPUT_EVENT.pack(0, 0, 1, 3, 1),   # 2
        INPUT_EVENT.pack(0, 0, 1, 4, 1),   # 3
        INPUT_EVENT.pack(0, 0, 1, 28, 1),  # enter
    ]
    device_path.write_bytes(b"".join(events))

    assert list(iter_barcode_scans(device_path)) == ["023"]
