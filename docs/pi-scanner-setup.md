# Raspberry Pi Scanner Setup

This setup runs two separate programs:

- `device_scanner.py` reads barcode input and posts scans to Grocy Ultimate Lookup.
- `gpio_state_controller.py` reads GPIO button presses and updates the shared scanner state file.

The shared state file carries the current mode, quantity, and location. The
barcode scanner reads it before every barcode scan.

## Pi And ESP32 Config

`scanner-buttons.example.json` is intentionally shaped so the logical control
mapping can be reused by both Pi scripts and future ESP32 firmware.

The Pi scripts use:

- `state_file`
- `controls.*.pin`
- `controls.*.action`
- `controls.*.value`
- `controls.*.key` for `--stdin` testing

Future ESP32 firmware can use:

- `device.id`
- `device.server_url`
- `scanner.type`
- `display.type`
- `controls.*.esp32_pin`
- the same `action` and `value` fields

ESP32 does not normally run Linux or systemd. The service installer in this repo
is for Raspberry Pi or another Linux host only. An ESP32 version would be
firmware under Arduino/ESP-IDF/FreeRTOS.

Your barcode scanner is USB-based. That means the ESP32 path needs an ESP32
board with USB host support, such as many ESP32-S2 or ESP32-S3 boards, or a
separate USB host module. A basic ESP32-WROOM board cannot directly read a USB
keyboard-wedge barcode scanner.

## Files

```text
scripts/device_scanner.py
scripts/gpio_state_controller.py
scripts/install_pi_scanner_services.sh
scanner-buttons.example.json
```

Default shared state path:

```text
/var/lib/grocy-scanner/state.json
```

Default GPIO config path:

```text
/etc/grocy-scanner/scanner-buttons.json
```

## JSON Button Configuration

Start from the example:

```bash
cp scanner-buttons.example.json scanner-buttons.json
```

Example mapping:

```json
{
  "schema_version": 1,
  "device": {
    "id": "kitchen-scanner",
    "server_url": "http://localhost:9290"
  },
  "scanner": {
    "type": "usb_hid",
    "submit_suffix": "enter"
  },
  "display": {
    "type": "text",
    "status_template": "{mode} x{quantity} @ {location}"
  },
  "state_file": "/var/lib/grocy-scanner/state.json",
  "controls": {
    "mode_add": { "pin": 5, "esp32_pin": 4, "key": "a", "action": "mode", "value": "add" },
    "mode_remove": { "pin": 6, "esp32_pin": 5, "key": "r", "action": "mode", "value": "remove" },
    "mode_set": { "pin": 13, "esp32_pin": 6, "key": "s", "action": "mode", "value": "set" },
    "quantity_up": { "pin": 19, "esp32_pin": 7, "key": "+", "action": "quantity_delta", "value": 1 },
    "quantity_down": { "pin": 26, "esp32_pin": 8, "key": "-", "action": "quantity_delta", "value": -1 },
    "quantity_zero": { "pin": 16, "esp32_pin": 9, "key": "0", "action": "quantity_set", "value": 0 },
    "location_next": { "pin": 20, "esp32_pin": 10, "key": "l", "action": "location_next" }
  }
}
```

Supported actions:

- `mode`: set mode to `add`, `remove`, or `set`
- `quantity_delta`: add or subtract from the current quantity
- `quantity_set`: set quantity directly, commonly `0`
- `location_next`: cycle to the next Grocy location

The `key` field is optional. It lets you test the same mapping with `--stdin`
before connecting GPIO buttons.

## Test Without GPIO Hardware

Run the controller in stdin mode:

```bash
python3 scripts/gpio_state_controller.py \
  --config scanner-buttons.example.json \
  --server http://localhost:9290 \
  --stdin
```

Type either a control name or a configured key:

```text
mode_add
+
l
0
q
```

The controller prints the current state after each change:

```text
Ready: ADD x2 @ Fridge
```

## Manual Two-Program Run

Terminal 1, barcode scanner:

```bash
python3 scripts/device_scanner.py \
  --server http://localhost:9290 \
  --device-id kitchen-pi \
  --token secret-token \
  --input-mode auto \
  --scanner-device auto \
  --state-file /var/lib/grocy-scanner/state.json
```

Terminal 2, GPIO controller:

```bash
python3 scripts/gpio_state_controller.py \
  --config /etc/grocy-scanner/scanner-buttons.json \
  --server http://localhost:9290
```

For local testing, replace the second command with `--stdin`.

To see what Linux scanner candidates the host can see:

```bash
python3 scripts/device_scanner.py --list-input-devices
```

If auto-detection picks the wrong device, rerun with an explicit path from
`/dev/input/by-id/...`:

```bash
python3 scripts/device_scanner.py \
  --server http://localhost:9290 \
  --device-id kitchen-pi \
  --token secret-token \
  --input-mode evdev \
  --scanner-device /dev/input/by-id/usb-Honeywell_Xenon-event-kbd \
  --state-file /var/lib/grocy-scanner/state.json
```

## Install As Linux Services

Inspect the generated config and systemd units first:

```bash
scripts/install_pi_scanner_services.sh \
  --dry-run \
  --install-dir "$PWD" \
  --server http://localhost:9290 \
  --device-id kitchen-pi \
  --token secret-token \
  --scanner-tty /dev/tty1
```

Install and start both services:

```bash
sudo scripts/install_pi_scanner_services.sh \
  --install-dir "$PWD" \
  --server http://localhost:9290 \
  --device-id kitchen-pi \
  --token secret-token \
  --scanner-tty /dev/tty1
```

On the server, require the same token with:

```text
SCANNER_DEVICE_TOKENS=kitchen-pi:secret-token
```

Leave `SCANNER_DEVICE_TOKENS` empty for unauthenticated local testing. Multiple
devices use comma-separated pairs:

```text
SCANNER_DEVICE_TOKENS=kitchen-pi:secret-token,pantry-pi:other-token
```

`device_scanner.py` sends a heartbeat at startup and after successful scans.
The server marks devices offline when their last heartbeat is older than
`SCANNER_DEVICE_OFFLINE_AFTER_SECONDS`.

The installer creates:

```text
/etc/systemd/system/grocy-device-scanner.service
/etc/systemd/system/grocy-gpio-state-controller.service
/etc/grocy-scanner/scanner-buttons.json
/var/lib/grocy-scanner/
```

It then runs:

```bash
systemctl daemon-reload
systemctl enable --now grocy-device-scanner.service grocy-gpio-state-controller.service
```

## Service Operations

Check status:

```bash
systemctl status grocy-device-scanner.service
systemctl status grocy-gpio-state-controller.service
```

Follow logs:

```bash
journalctl -u grocy-device-scanner.service -f
journalctl -u grocy-gpio-state-controller.service -f
```

Restart after config changes:

```bash
sudo systemctl restart grocy-gpio-state-controller.service
```

Stop both services:

```bash
sudo systemctl stop grocy-device-scanner.service grocy-gpio-state-controller.service
```

## Barcode Scanner Input

`device_scanner.py` now prefers Linux input-event binding when possible. In
`--input-mode auto`, it:

- scans `/dev/input/by-id` and `/dev/input/event*`
- prefers devices whose metadata looks scanner-like
- binds the best match directly so your normal keyboard can still be used
- falls back to the original TTY/stdin loop if no likely scanner is found

If scans do not appear in the service logs:

- run `python3 scripts/device_scanner.py --list-input-devices`
- confirm the scanner sends Enter after each barcode
- rerun with `--input-mode evdev --scanner-device /dev/input/by-id/...`
- if direct device binding is not available, fall back to `--scanner-tty /dev/tty1` or another TTY

Direct `/dev/input/by-id/...` binding is the most reliable option because the
stable symlink survives better than raw `eventN` numbering across reboots.
