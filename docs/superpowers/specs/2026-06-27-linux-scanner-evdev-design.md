# Linux Scanner Evdev Design

## Goal

Let a Linux or Raspberry Pi host keep using its normal keyboard while a USB
barcode scanner feeds `device_scanner.py` directly.

## Approved Design

The scanner client keeps the current stdin/TTY path as a fallback, but adds a
preferred Linux input-event path:

- `device_scanner.py --input-mode auto` first discovers likely scanner devices
  from `/dev/input/by-id` and `/dev/input/event*`
- the detector scores candidates conservatively, favoring scanner-like names
  and stable `/dev/input/by-id/...-event-kbd` symlinks
- if a likely scanner is found, the client reads Linux key events directly from
  that device and reconstructs barcode strings until Enter
- if no likely scanner is found, the client falls back to the current stdin loop
- operators can inspect candidates with `--list-input-devices` or bind an
  explicit path with `--scanner-device /dev/input/by-id/...`

## Boundaries

- Scanner detection and Linux event decoding live in `scripts/linux_input.py`
- HTTP scan posting, heartbeat behavior, and shared state-file behavior stay in
  `scripts/device_scanner.py`
- systemd installer defaults to auto-detect mode while preserving TTY fallback

## Failure Handling

- If direct device binding is requested and the device cannot be opened, print a
  specific permission or not-found error and exit non-zero
- Auto mode only binds when the candidate score is strong enough; generic
  keyboards should not be claimed as scanners

## Testing

- Unit-test candidate discovery and scoring against fake `/dev/input` and
  `/sys/class/input` trees
- Unit-test Linux key-event decoding into complete barcode strings
- Keep existing device-scanner payload tests and installer dry-run tests green
