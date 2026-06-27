# Linux Scanner Evdev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Linux scanner auto-detection and direct input-device binding without removing the existing TTY/stdin fallback.

**Architecture:** A new `scripts/linux_input.py` module owns device discovery, scoring, and raw Linux key-event decoding. `scripts/device_scanner.py` chooses between an auto-detected evdev device, an explicit evdev path, or the existing stdin loop while preserving existing scan payload and heartbeat behavior.

**Tech Stack:** Python 3, stdlib `struct`/`pathlib`, pytest, existing systemd installer shell script

---

### Task 1: Lock discovery behavior with tests

**Files:**
- Create: `tests/test_linux_input.py`
- Create: `tests/test_device_scanner_linux.py`
- Test: `tests/test_pi_service_installer.py`

- [ ] **Step 1: Write failing discovery and source-selection tests**
- [ ] **Step 2: Run `rtk .venv/bin/python -m pytest tests/test_linux_input.py tests/test_device_scanner_linux.py tests/test_pi_service_installer.py -q` and verify they fail for missing symbols and installer args**

### Task 2: Implement Linux input discovery and runtime selection

**Files:**
- Create: `scripts/linux_input.py`
- Modify: `scripts/device_scanner.py`

- [ ] **Step 1: Add `InputDeviceCandidate`, conservative scanner scoring, and `/dev/input` discovery**
- [ ] **Step 2: Add raw Linux key-event decoding that yields completed barcode strings on Enter**
- [ ] **Step 3: Add `--input-mode`, `--scanner-device`, and `--list-input-devices` to `device_scanner.py`**
- [ ] **Step 4: Run `rtk .venv/bin/python -m pytest tests/test_linux_input.py tests/test_device_scanner_linux.py tests/test_device_scanner_client.py -q` and verify green**

### Task 3: Update installer and operator docs

**Files:**
- Modify: `scripts/install_pi_scanner_services.sh`
- Modify: `README.md`
- Modify: `docs/pi-scanner-setup.md`

- [ ] **Step 1: Change the service unit to pass `--input-mode auto --scanner-device auto` while preserving TTY fallback**
- [ ] **Step 2: Document `--list-input-devices`, explicit device binding, and the fallback behavior**
- [ ] **Step 3: Run `rtk .venv/bin/python -m pytest tests/test_pi_service_installer.py tests/test_linux_input.py tests/test_device_scanner_linux.py tests/test_device_scanner_client.py -q` and verify green**
