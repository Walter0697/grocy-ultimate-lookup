#!/usr/bin/env python3
"""Prototype barcode scanner client for a Raspberry Pi or Linux terminal."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    from scanner_state import DEFAULT_STATE_PATH, payload_from_state, read_state
except ImportError:  # pragma: no cover - used when imported as scripts.device_scanner
    from scripts.scanner_state import DEFAULT_STATE_PATH, payload_from_state, read_state


def auth_headers(token: str | None) -> dict[str, str]:
    return {"X-Scanner-Token": token} if token else {}


def post_json(base_url: str, path: str, payload: dict, token: str | None = None, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", **auth_headers(token)}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_scan(base_url: str, payload: dict, token: str | None = None) -> dict:
    return post_json(base_url, "/scanner/scan", payload, token=token, timeout=60)


def post_heartbeat(base_url: str, payload: dict, token: str | None = None) -> dict:
    return post_json(base_url, "/scanner/heartbeat", payload, token=token, timeout=20)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send barcode scans to Grocy Ultimate Lookup.")
    parser.add_argument("--server", default="http://localhost:9290", help="Grocy Ultimate Lookup base URL")
    parser.add_argument("--device-id", default="kitchen-pi", help="Device ID shown in the dashboard")
    parser.add_argument("--token", help="Optional scanner device token sent as X-Scanner-Token")
    parser.add_argument("--mode", choices=["add", "remove", "set"], default="add", help="Stock operation mode")
    parser.add_argument("--quantity", type=float, default=1, help="Quantity for the stock operation")
    parser.add_argument("--location-id", type=int, help="Optional Grocy location ID")
    parser.add_argument(
        "--state-file",
        help=f"Read mode/quantity/location from this JSON file before each scan, e.g. {DEFAULT_STATE_PATH}",
    )
    parser.add_argument("barcode", nargs="?", help="Barcode to send once; omit for scanner stdin loop")
    return parser.parse_args()


def payload(args: argparse.Namespace, barcode: str) -> dict:
    if args.state_file:
        return payload_from_state(args.device_id, barcode, read_state(args.state_file))
    data = {
        "device_id": args.device_id,
        "barcode": barcode.strip(),
        "mode": args.mode,
        "quantity": args.quantity,
    }
    if args.location_id:
        data["location_id"] = args.location_id
    return data


def heartbeat_payload(args: argparse.Namespace) -> dict:
    if args.state_file:
        state = read_state(args.state_file)
        data = {
            "device_id": args.device_id,
            "mode": state.mode,
            "quantity": state.quantity,
            "location_id": state.location_id,
            "location_name": state.location_name,
            "version": "device_scanner.py",
        }
    else:
        data = {
            "device_id": args.device_id,
            "mode": args.mode,
            "quantity": args.quantity,
            "location_id": args.location_id,
            "version": "device_scanner.py",
        }
    return {key: value for key, value in data.items() if value is not None}


def print_response(result: dict) -> None:
    marker = "REVIEW" if result.get("needs_review") else "OK"
    print(f"[{marker}] {result.get('message')}")
    print(json.dumps(result, indent=2))


def scan_once(args: argparse.Namespace, barcode: str) -> int:
    if not barcode.strip():
        return 0
    try:
        state = read_state(args.state_file) if args.state_file else None
        if args.state_file:
            print(f"Scanning {barcode.strip()} with {state.status()}", file=sys.stderr)
            print("BUSY: sending scan to server; ignore scanner input until Ready is shown.", file=sys.stderr)
        data = payload_from_state(args.device_id, barcode, state) if state else payload(args, barcode)
        print_response(post_scan(args.server, data, token=args.token))
        try:
            post_heartbeat(args.server, heartbeat_payload(args), token=args.token)
        except Exception as exc:
            print(f"Heartbeat failed: {exc}", file=sys.stderr)
        if args.state_file:
            print(f"Ready: {read_state(args.state_file).status()}", file=sys.stderr)
        return 0
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
    except Exception as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()
    if args.barcode:
        return scan_once(args, args.barcode)

    if args.state_file:
        print(f"Ready: {read_state(args.state_file).status()}", file=sys.stderr)
        print("Scan barcode then Enter. State is reloaded from the state file before each scan.", file=sys.stderr)
    else:
        print("Ready. Scan barcode then Enter. Press Ctrl+C to stop.", file=sys.stderr)
    failures = 0
    try:
        post_heartbeat(args.server, heartbeat_payload(args), token=args.token)
    except Exception as exc:
        print(f"Heartbeat failed: {exc}", file=sys.stderr)
    try:
        for line in sys.stdin:
            failures += scan_once(args, line)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
