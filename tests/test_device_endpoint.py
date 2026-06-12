from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, scanner


def test_scanner_scan_endpoint_uses_device_friendly_payload(monkeypatch) -> None:
    async def fake_process_device_scan(request):
        assert request.device_id == "kitchen-pi"
        assert request.barcode == "123456"
        assert request.mode == "add"
        assert request.quantity == 1
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

    monkeypatch.setattr(scanner, "process_device_scan", fake_process_device_scan)
    response = TestClient(app).post(
        "/scanner/scan",
        json={"device_id": "kitchen-pi", "barcode": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == "kitchen-pi-event"
    assert response.json()["needs_review"] is False


def test_scanner_scan_rejects_missing_token_when_device_auth_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")

    response = TestClient(app).post(
        "/scanner/scan",
        json={"device_id": "kitchen-pi", "barcode": "123456"},
    )

    assert response.status_code == 401


def test_scanner_scan_accepts_matching_device_token(monkeypatch) -> None:
    async def fake_process_device_scan(request):
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

    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")
    monkeypatch.setattr(scanner, "process_device_scan", fake_process_device_scan)

    response = TestClient(app).post(
        "/scanner/scan",
        headers={"X-Scanner-Token": "secret-token"},
        json={"device_id": "kitchen-pi", "barcode": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == "kitchen-pi-event"


def test_scanner_heartbeat_records_device_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "kitchen-pi:secret-token")

    response = TestClient(app).post(
        "/scanner/heartbeat",
        headers={"X-Scanner-Token": "secret-token"},
        json={
            "device_id": "kitchen-pi",
            "mode": "add",
            "quantity": 2,
            "location_id": 3,
            "location_name": "Pantry",
            "version": "pi-script",
        },
    )

    assert response.status_code == 200
    assert response.json()["device_id"] == "kitchen-pi"
    assert response.json()["online"] is True
    assert response.json()["mode"] == "add"
    assert response.json()["quantity"] == 2


def test_scanner_devices_lists_last_heartbeat(monkeypatch) -> None:
    monkeypatch.setattr(settings, "scanner_device_tokens", "")
    client = TestClient(app)

    client.post(
        "/scanner/heartbeat",
        json={"device_id": "list-pi", "mode": "remove", "quantity": 1},
    )
    response = client.get("/scanner/devices")

    assert response.status_code == 200
    device = next(item for item in response.json() if item["device_id"] == "list-pi")
    assert device["online"] is True
    assert device["mode"] == "remove"


def test_dashboard_uses_versioned_local_assets() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "/static/app.js?v=" in response.text
    assert "/static/styles.css?v=" in response.text
    assert "/static/scan-dialog.css?v=" in response.text


def test_dashboard_static_includes_scanner_device_status_panel() -> None:
    index = (app.router.routes[0].endpoint.__globals__["static_path"] / "index.html").read_text()
    script = (app.router.routes[0].endpoint.__globals__["static_path"] / "app.js").read_text()

    assert 'id="scanner-status"' in index
    assert "renderScannerStatus" in script
    assert "scanner_devices" in script
