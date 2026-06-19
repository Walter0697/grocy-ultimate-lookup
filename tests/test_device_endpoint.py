import asyncio

from fastapi import HTTPException

from app.config import settings
from app.main import (
    app,
    create_device_scan,
    list_scanner_devices,
    scanner,
    scanner_heartbeat,
    static_path,
    versioned_index_html,
)
from app.models import DeviceHeartbeatRequest, DeviceScanRequest


def run(coro):
    return asyncio.run(coro)


def applied_response(request):
    return {
        "event_id": "kitchen-pi-event",
        "status": "applied",
        "barcode": request.barcode,
        "mode": request.mode,
        "quantity": request.quantity,
        "product_name": "Known Product",
        "stock_before": 1,
        "stock_after": 2,
        "needs_review": False,
        "message": "Known Product: stock is now 2",
    }


def test_scanner_scan_endpoint_uses_device_friendly_payload(monkeypatch) -> None:
    async def fake_process_device_scan(request):
        assert request.device_id == "kitchen-pi"
        assert request.barcode == "123456"
        assert request.mode == "add"
        assert request.quantity == 1
        return applied_response(request)

    monkeypatch.setattr(settings, "scanner_device_tokens", "")
    monkeypatch.setattr(scanner, "process_device_scan", fake_process_device_scan)

    response = run(create_device_scan(DeviceScanRequest(device_id="kitchen-pi", barcode="123456")))

    assert response["event_id"] == "kitchen-pi-event"
    assert response["needs_review"] is False


def test_scanner_scan_rejects_missing_token_when_device_auth_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")

    try:
        run(create_device_scan(DeviceScanRequest(device_id="kitchen-pi", barcode="123456"), x_scanner_token=None))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("missing scanner token was accepted")


def test_scanner_scan_accepts_matching_device_token(monkeypatch) -> None:
    async def fake_process_device_scan(request):
        return applied_response(request)

    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")
    monkeypatch.setattr(scanner, "process_device_scan", fake_process_device_scan)

    response = run(
        create_device_scan(
            DeviceScanRequest(device_id="kitchen-pi", barcode="123456"),
            x_scanner_token="secret-token",
        )
    )

    assert response["event_id"] == "kitchen-pi-event"


def test_scanner_heartbeat_records_device_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")

    response = run(
        scanner_heartbeat(
            DeviceHeartbeatRequest(
                device_id="kitchen-pi",
                mode="add",
                quantity=2,
                location_id=3,
                location_name="Pantry",
                version="pi-script",
            ),
            x_scanner_token="secret-token",
        )
    )

    assert response.device_id == "kitchen-pi"
    assert response.online is True
    assert response.mode == "add"
    assert response.quantity == 2


def test_scanner_devices_lists_last_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "")

    run(scanner_heartbeat(DeviceHeartbeatRequest(device_id="list-pi", mode="remove", quantity=1)))
    response = run(list_scanner_devices())

    device = next(item for item in response if item.device_id == "list-pi")
    assert device.online is True
    assert device.mode == "remove"


def test_dashboard_uses_versioned_local_assets() -> None:
    response = versioned_index_html()

    assert "/static/app.js?v=" in response
    assert "/static/styles.css?v=" in response
    assert "/static/scan-dialog.css?v=" in response


def test_dashboard_static_includes_scanner_device_status_panel() -> None:
    index = (static_path / "index.html").read_text()
    script = (static_path / "app.js").read_text()

    assert 'id="scanner-status"' in index
    assert "renderScannerStatus" in script
    assert "scanner_devices" in script


def test_dashboard_links_to_settings_page() -> None:
    index = (static_path / "index.html").read_text()
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()

    assert '<a class="settings-button" href="/settings">Settings</a>' in index
    assert 'id="community-catalog-form"' in settings_html
    assert "/settings/community-catalog" in settings_script
