from argparse import Namespace
from pathlib import Path

from scripts.device_scanner import choose_input_source
from scripts.linux_input import InputDeviceCandidate


def test_choose_input_source_uses_explicit_scanner_device() -> None:
    args = Namespace(input_mode="auto", scanner_device="/dev/input/by-id/usb-scanner-event-kbd")

    chosen = choose_input_source(args, detected=None)

    assert chosen == "/dev/input/by-id/usb-scanner-event-kbd"


def test_choose_input_source_uses_detected_scanner_for_auto_mode() -> None:
    args = Namespace(input_mode="auto", scanner_device="auto")
    detected = InputDeviceCandidate(
        event_path="/dev/input/event4",
        stable_path="/dev/input/by-id/usb-scanner-event-kbd",
        name="Honeywell Scanner",
        vendor_id="0c2e",
        product_id="0b61",
        score=8,
        reasons=["name:scanner"],
    )

    chosen = choose_input_source(args, detected=detected)

    assert chosen == "/dev/input/by-id/usb-scanner-event-kbd"


def test_choose_input_source_returns_none_when_auto_mode_finds_no_scanner() -> None:
    args = Namespace(input_mode="auto", scanner_device="auto")

    assert choose_input_source(args, detected=None) is None
