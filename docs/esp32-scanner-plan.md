# ESP32 Scanner Plan

ESP32 does not install or run the Python scanner scripts. It needs firmware.

The shared config file is still useful because it defines the logical controls:

```text
scanner-buttons.example.json
```

Future ESP32 firmware should consume the same concepts:

- `device.id`
- `device.server_url`
- `scanner.type`
- `display.type`
- `controls.*.esp32_pin`
- `controls.*.action`
- `controls.*.value`

## USB Scanner Requirement

The purchased barcode scanner is USB-based. For ESP32, choose hardware with USB
host support:

- ESP32-S2 or ESP32-S3 board with exposed USB OTG/host capability
- or a separate USB host module/shield connected to the ESP32

A common ESP32-WROOM board is not enough by itself because it cannot directly
host a USB keyboard-wedge scanner.

## Firmware Shape

The ESP32 firmware should:

1. Connect to Wi-Fi.
2. Read the USB HID barcode scanner.
3. Track current mode, quantity, and location in memory.
4. Read buttons or rotary encoder using `esp32_pin` mappings.
5. Print current state on a text display.
6. Send scans to:

```text
POST /scanner/scan
```

with:

```json
{
  "device_id": "kitchen-scanner",
  "barcode": "066200032500",
  "mode": "add",
  "quantity": 1,
  "location_id": 2
}
```

When `SCANNER_DEVICE_TOKENS` is configured on the server, firmware must send:

```text
X-Scanner-Token: <device token>
```

The token is matched against the `device_id`.

Firmware should also send heartbeat updates to:

```text
POST /scanner/heartbeat
```

with:

```json
{
  "device_id": "kitchen-scanner",
  "mode": "add",
  "quantity": 1,
  "location_id": 2,
  "location_name": "Fridge",
  "version": "esp32-firmware"
}
```

## Recommended Install Path

Use PlatformIO for the eventual firmware project:

```bash
pio run --target upload
```

Start with a `config.h` generated or copied from the JSON values. Later, add a
first-boot Wi-Fi/config portal if editing and flashing becomes annoying.

## Pi Versus ESP32

Pi:

```text
Python scripts + systemd services + shared state file
```

ESP32:

```text
C++ firmware + USB host + Wi-Fi HTTP client + local in-memory state
```

The API contract and logical controls stay the same across both.
