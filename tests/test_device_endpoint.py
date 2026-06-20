import asyncio
from io import BytesIO

from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.main import (
    app,
    create_device_scan,
    dashboard_options,
    delete_scan_event,
    list_scanner_devices,
    preview_scan,
    scanner,
    scanner_heartbeat,
    static_path,
    upload_product_image,
    uploaded_images_path,
    versioned_index_html,
)
from app.grocy import GrocyError
from app.models import DeviceHeartbeatRequest, DeviceScanRequest, ScanEventRequest


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


def test_settings_page_uses_pending_product_review_dialog() -> None:
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()

    assert 'id="review-community-catalog"' in settings_html
    assert 'id="pending-products-dialog"' in settings_html
    assert 'id="push-community-catalog"' not in settings_html
    assert 'id="discard-community-catalog"' not in settings_html
    assert "/settings/community-catalog/pending-products" in settings_script
    assert "/settings/community-catalog/push-products" in settings_script
    assert "/settings/community-catalog/discard-products" in settings_script


def test_delete_scan_event_removes_dashboard_review_item() -> None:
    scanner.store.delete("delete-endpoint-event")
    event, created = scanner.store.create(
        ScanEventRequest(
            event_id="delete-endpoint-event",
            device_id="dashboard-manual",
            barcode="123456",
            mode="add",
            quantity=1,
        )
    )
    assert created is True
    assert event["event_id"] == "delete-endpoint-event"

    run(delete_scan_event("delete-endpoint-event"))

    assert scanner.store.get("delete-endpoint-event") is None


def test_delete_scan_event_returns_404_for_missing_event() -> None:
    try:
        run(delete_scan_event("missing-delete-event"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing scan event delete did not return 404")


def test_product_image_upload_returns_fetchable_image_url() -> None:
    upload = UploadFile(
        filename="product.jpg",
        file=BytesIO(b"fake-jpeg"),
        headers=Headers({"content-type": "image/jpeg"}),
    )

    response = run(upload_product_image(upload))

    assert response["image_url"].startswith("http://lookup.test/uploaded-images/")
    assert response["preview_url"].startswith("/uploaded-images/")
    assert (uploaded_images_path / response["preview_url"].rsplit("/", 1)[1]).read_bytes() == b"fake-jpeg"


def test_product_image_upload_rejects_non_images() -> None:
    upload = UploadFile(
        filename="product.txt",
        file=BytesIO(b"not an image"),
        headers=Headers({"content-type": "text/plain"}),
    )

    try:
        run(upload_product_image(upload))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("non-image upload was accepted")


def test_dashboard_options_maps_grocy_errors_to_json_api_error(monkeypatch) -> None:
    async def fake_options():
        raise GrocyError("Grocy returned non-JSON response: setup is missing")

    monkeypatch.setattr(scanner, "options", fake_options)

    try:
        run(dashboard_options())
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "setup is missing" in exc.detail
    else:
        raise AssertionError("GrocyError was not converted to an API error")


def test_scan_preview_maps_grocy_errors_to_json_api_error(monkeypatch) -> None:
    async def fake_preview(barcode):
        raise GrocyError("Grocy returned non-JSON response: setup is missing")

    monkeypatch.setattr(scanner, "preview", fake_preview)

    try:
        run(preview_scan("123456"))
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "setup is missing" in exc.detail
    else:
        raise AssertionError("GrocyError was not converted to an API error")
