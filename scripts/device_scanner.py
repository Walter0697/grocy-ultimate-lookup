#!/usr/bin/env python3
"""Prototype barcode scanner client for a Raspberry Pi or Linux terminal."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def post_scan(base_url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/scanner/scan",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send barcode scans to Grocy Ultimate Lookup.")
    parser.add_argument("--server", default="http://localhost:9290", help="Grocy Ultimate Lookup base URL")
    parser.add_argument("--device-id", default="kitchen-pi", help="Device ID shown in the dashboard")
    parser.add_argument("--mode", choices=["add", "remove", "set"], default="add", help="Stock operation mode")
    parser.add_argument("--quantity", type=float, default=1, help="Quantity for the stock operation")
    parser.add_argument("--location-id", type=int, help="Optional Grocy location ID")
    parser.add_argument("barcode", nargs="?", help="Barcode to send once; omit for scanner stdin loop")
    return parser.parse_args()


def payload(args: argparse.Namespace, barcode: str) -> dict:
    data = {
        "device_id": args.device_id,
        "barcode": barcode.strip(),
        "mode": args.mode,
        "quantity": args.quantity,
    }
    if args.location_id:
        data["location_id"] = args.location_id
    return data


def print_response(result: dict) -> None:
    marker = "REVIEW" if result.get("needs_review") else "OK"
    print(f"[{marker}] {result.get('message')}")
    print(json.dumps(result, indent=2))


def scan_once(args: argparse.Namespace, barcode: str) -> int:
    if not barcode.strip():
        return 0
    try:
        print_response(post_scan(args.server, payload(args, barcode)))
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

    print("Ready. Scan barcode then Enter. Press Ctrl+C to stop.", file=sys.stderr)
    failures = 0
    try:
        for line in sys.stdin:
            failures += scan_once(args, line)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
