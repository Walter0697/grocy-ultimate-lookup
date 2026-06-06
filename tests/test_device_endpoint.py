from fastapi.testclient import TestClient

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
