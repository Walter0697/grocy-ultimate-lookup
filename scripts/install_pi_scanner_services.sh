#!/usr/bin/env bash
set -euo pipefail

install_dir="$(pwd)"
python_bin="/usr/bin/python3"
server="http://localhost:9290"
device_id="kitchen-pi"
state_file="/var/lib/grocy-scanner/state.json"
config_file="/etc/grocy-scanner/scanner-buttons.json"
scanner_tty="/dev/tty1"
service_user="root"
scanner_token=""
dry_run="false"

usage() {
  cat <<'EOF'
Usage: scripts/install_pi_scanner_services.sh [options]

Install Raspberry Pi systemd services for:
  - grocy-device-scanner.service: reads barcode stdin from a Linux TTY
  - grocy-gpio-state-controller.service: maps GPIO buttons to scanner state

Options:
  --install-dir PATH   Project checkout path. Default: current directory.
  --python PATH        Python executable for services. Default: /usr/bin/python3.
  --server URL         Grocy Ultimate Lookup base URL. Default: http://localhost:9290.
  --device-id ID       Scanner device ID. Default: kitchen-pi.
  --state-file PATH    Shared scanner state file. Default: /var/lib/grocy-scanner/state.json.
  --config PATH        GPIO button JSON config. Default: /etc/grocy-scanner/scanner-buttons.json.
  --scanner-tty PATH   Fallback TTY if auto device detection finds no scanner. Default: /dev/tty1.
  --token TOKEN        Optional scanner token sent as X-Scanner-Token.
  --user USER          Service user. Default: root.
  --dry-run            Print generated files and commands without installing.
  -h, --help           Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) install_dir="$2"; shift 2 ;;
    --python) python_bin="$2"; shift 2 ;;
    --server) server="$2"; shift 2 ;;
    --device-id) device_id="$2"; shift 2 ;;
    --state-file) state_file="$2"; shift 2 ;;
    --config) config_file="$2"; shift 2 ;;
    --scanner-tty) scanner_tty="$2"; shift 2 ;;
    --token) scanner_token="$2"; shift 2 ;;
    --user) service_user="$2"; shift 2 ;;
    --dry-run) dry_run="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$dry_run" != "true" && "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo, or use --dry-run to inspect generated units." >&2
  exit 1
fi

install_dir="${install_dir%/}"
state_dir="$(dirname "$state_file")"
config_dir="$(dirname "$config_file")"
token_arg=""
if [[ -n "$scanner_token" ]]; then
  token_arg=" --token ${scanner_token}"
fi

device_unit="[Unit]
Description=Grocy barcode scanner stdin client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${service_user}
WorkingDirectory=${install_dir}
Environment=PYTHONUNBUFFERED=1
StandardInput=tty
TTYPath=${scanner_tty}
TTYReset=no
TTYVHangup=no
ExecStart=${python_bin} ${install_dir}/scripts/device_scanner.py --server ${server} --device-id ${device_id}${token_arg} --input-mode auto --scanner-device auto --state-file ${state_file}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"

gpio_unit="[Unit]
Description=Grocy GPIO scanner state controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${service_user}
WorkingDirectory=${install_dir}
Environment=PYTHONUNBUFFERED=1
ExecStart=${python_bin} ${install_dir}/scripts/gpio_state_controller.py --config ${config_file} --server ${server}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"

default_config="{
  \"schema_version\": 1,
  \"device\": {
    \"id\": \"${device_id}\",
    \"server_url\": \"${server}\"
  },
  \"scanner\": {
    \"type\": \"usb_hid\",
    \"submit_suffix\": \"enter\",
    \"notes\": \"USB keyboard-wedge scanner. Pi reads it from the configured TTY; ESP32 needs USB host support.\"
  },
  \"display\": {
    \"type\": \"text\",
    \"status_template\": \"{mode} x{quantity} @ {location}\"
  },
  \"state_file\": \"${state_file}\",
  \"controls\": {
    \"mode_add\": { \"pin\": 5, \"esp32_pin\": 4, \"key\": \"a\", \"action\": \"mode\", \"value\": \"add\" },
    \"mode_remove\": { \"pin\": 6, \"esp32_pin\": 5, \"key\": \"r\", \"action\": \"mode\", \"value\": \"remove\" },
    \"mode_set\": { \"pin\": 13, \"esp32_pin\": 6, \"key\": \"s\", \"action\": \"mode\", \"value\": \"set\" },
    \"quantity_up\": { \"pin\": 19, \"esp32_pin\": 7, \"key\": \"+\", \"action\": \"quantity_delta\", \"value\": 1 },
    \"quantity_down\": { \"pin\": 26, \"esp32_pin\": 8, \"key\": \"-\", \"action\": \"quantity_delta\", \"value\": -1 },
    \"quantity_zero\": { \"pin\": 16, \"esp32_pin\": 9, \"key\": \"0\", \"action\": \"quantity_set\", \"value\": 0 },
    \"location_next\": { \"pin\": 20, \"esp32_pin\": 10, \"key\": \"l\", \"action\": \"location_next\" }
  }
}
"

if [[ "$dry_run" == "true" ]]; then
  cat <<EOF
Would create ${state_dir}
Would create ${config_dir}

== ${config_file} ==
${default_config}
== /etc/systemd/system/grocy-device-scanner.service ==
${device_unit}
== /etc/systemd/system/grocy-gpio-state-controller.service ==
${gpio_unit}
Would run:
  systemctl daemon-reload
  systemctl enable --now grocy-device-scanner.service grocy-gpio-state-controller.service
EOF
  exit 0
fi

mkdir -p "$state_dir" "$config_dir"

if [[ ! -f "$config_file" ]]; then
  printf '%s' "$default_config" > "$config_file"
  chmod 0644 "$config_file"
fi

printf '%s' "$device_unit" > /etc/systemd/system/grocy-device-scanner.service
printf '%s' "$gpio_unit" > /etc/systemd/system/grocy-gpio-state-controller.service

systemctl daemon-reload
systemctl enable --now grocy-device-scanner.service grocy-gpio-state-controller.service

cat <<EOF
Installed and started:
  grocy-device-scanner.service
  grocy-gpio-state-controller.service

Check status:
  systemctl status grocy-device-scanner.service
  systemctl status grocy-gpio-state-controller.service

Edit button mapping:
  ${config_file}
EOF
