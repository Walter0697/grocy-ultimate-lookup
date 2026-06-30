import asyncio
from io import BytesIO

import httpx
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.main import (
    app,
    create_device_scan,
    dashboard_edit_product,
    dashboard_options,
    delete_scan_event,
    list_scanner_devices,
    preview_scan,
    seed_grocy_units,
    scanner,
    scanner_heartbeat,
    static_path,
    get_app_version,
    upload_product_image,
    uploaded_images_path,
    versioned_index_html,
)
from app.grocy import GrocyError
from app.models import DashboardProductUpdate, DeviceHeartbeatRequest, DeviceScanRequest, ScanEventRequest


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


def test_dashboard_renders_subtle_app_version_badge() -> None:
    response = versioned_index_html()

    assert 'class="app-version-badge"' in response
    assert f">v{get_app_version()}<" in response


def test_dashboard_static_includes_scanner_device_status_panel() -> None:
    index = (static_path / "index.html").read_text()
    script = (static_path / "app.js").read_text()

    assert 'id="scanner-status"' in index
    assert "renderScannerStatus" in script
    assert "scanner_devices" in script


def test_dashboard_static_includes_product_editor_controls() -> None:
    index = (static_path / "index.html").read_text()
    script = (static_path / "app.js").read_text()

    assert 'id="products-panel"' in index
    assert 'id="product-grid"' in index
    assert 'id="product-edit-dialog"' in index
    assert 'id="product-edit-content"' in index
    assert "renderProducts" in script
    assert "openProductEditDialog" in script
    assert 'id="product-edit-form"' in script
    assert "Save product" in script
    assert "/dashboard/products" in script


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


def test_settings_page_includes_inline_community_catalog_source_list() -> None:
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()

    assert 'id="catalog-source-list"' in settings_html
    assert 'id="catalog-sources-dialog"' not in settings_html
    assert 'id="add-catalog-source-dialog"' in settings_html
    assert 'id="open-add-catalog-source"' in settings_html
    assert "/settings/community-catalog-sources" in settings_script
    assert "initCatalogSourceSortable" in settings_script
    assert "catalog-source-grip" in settings_script
    assert "source-toggle" in settings_script
    assert "source-remove" in settings_script
    assert "source-up" not in settings_script
    assert "source-down" not in settings_script
    assert "updateCatalogSourceButtonLabel" not in settings_script


def test_settings_page_has_shared_github_access_section() -> None:
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()

    assert 'id="github-access-form"' in settings_html
    assert "Catalog credentials" in settings_html
    assert "githubAccessFormData" in settings_script


def test_settings_page_uses_sortable_search_provider_rows() -> None:
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()

    assert "/static/vendor/sortable.min.js" in settings_html
    assert "Sortable.create" in settings_script
    assert "Grocy current data" in settings_script
    assert "Recommend first" in settings_script
    assert "Ultimate Lookup cache" in settings_script
    assert "Recommend second" in settings_script
    assert "Community catalogs" in settings_script
    assert "Recommend third" in settings_script
    assert "Codex based final fallback" in settings_script
    assert "Recommend last" in settings_script
    assert "Set an LLM API key and model first" in settings_script
    assert "Set up Codex auth/runtime first" in settings_script
    assert ".search-provider-card:not(.is-unavailable)" in settings_script
    assert 'filter: ".is-unavailable"' in settings_script
    assert 'draggable="true"' not in settings_script
    assert 'addEventListener("dragstart"' not in settings_script


def test_settings_page_includes_grocy_units_seed_section() -> None:
    settings_html = (static_path / "settings.html").read_text()
    settings_script = (static_path / "settings.js").read_text()
    settings_css = (static_path / "settings.css").read_text()

    assert "Grocy Units" in settings_html
    assert 'id="seed-grocy-units"' in settings_html
    assert 'id="grocy-units-result"' in settings_html
    assert 'class="settings-status"' in settings_html
    assert "/settings/grocy-units/seed" in settings_script
    assert "renderGrocyUnitsList(result.added" in settings_script
    assert "renderGrocyUnitsList(result.already_exists" in settings_script
    assert "renderGrocyUnitsList(result.failed" in settings_script
    assert "item.name" in settings_script
    assert "item.error" in settings_script
    assert 'const seedGrocyUnitsButton = $("#seed-grocy-units")' in settings_script
    assert "setButtonBusy(button, true, \"Seeding...\")" in settings_script
    assert ".settings-status-card" not in settings_css


def test_seed_grocy_units_returns_added_existing_and_failed(monkeypatch) -> None:
    async def fake_get_objects(entity):
        assert entity == "quantity_units"
        return [{"name": "piece"}]

    created = []

    async def fake_create_quantity_unit(name):
        created.append(name)
        if name == "bag":
            raise RuntimeError("boom")
        return {"created_object_id": 1}

    monkeypatch.setattr(scanner.grocy, "get_objects", fake_get_objects)
    monkeypatch.setattr(scanner.grocy, "create_quantity_unit", fake_create_quantity_unit)
    monkeypatch.setattr("app.grocy_units.COMMON_GROCY_UNITS", ["piece", "box", "bag"])

    result = run(seed_grocy_units())

    assert result["added"] == ["box"]
    assert result["already_exists"] == ["piece"]
    assert result["failed"] == [{"name": "bag", "error": "boom"}]


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


def test_dashboard_edit_product_forwards_success(monkeypatch) -> None:
    product = DashboardProductUpdate(
        name="Corrected Product",
        location_id=4,
        qu_id_stock=7,
        qu_id_purchase=7,
        qu_factor_purchase_to_stock=1,
    )

    async def fake_update_dashboard_product(product_id, payload):
        assert product_id == 7
        assert payload == product
        return {"product_id": 7, "name": "Corrected Product", "editable": True}

    monkeypatch.setattr(scanner, "update_dashboard_product", fake_update_dashboard_product)

    response = run(dashboard_edit_product(7, product))

    assert response == {"product_id": 7, "name": "Corrected Product", "editable": True}


def test_dashboard_edit_product_maps_unowned_product_to_403(monkeypatch) -> None:
    async def fake_update_dashboard_product(product_id, payload):
        raise PermissionError("Only auto-created products can be edited from this dashboard")

    monkeypatch.setattr(scanner, "update_dashboard_product", fake_update_dashboard_product)

    try:
        run(
            dashboard_edit_product(
                7,
                DashboardProductUpdate(
                    name="Corrected Product",
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Only auto-created products can be edited from this dashboard"
    else:
        raise AssertionError("PermissionError was not converted to a 403 API error")


def test_dashboard_edit_product_maps_missing_product_to_404(monkeypatch) -> None:
    async def fake_update_dashboard_product(product_id, payload):
        raise KeyError(product_id)

    monkeypatch.setattr(scanner, "update_dashboard_product", fake_update_dashboard_product)

    try:
        run(
            dashboard_edit_product(
                7,
                DashboardProductUpdate(
                    name="Corrected Product",
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Dashboard product not found"
    else:
        raise AssertionError("KeyError was not converted to a 404 API error")


def test_dashboard_edit_product_route_returns_404(monkeypatch) -> None:
    async def fake_update_dashboard_product(product_id, payload):
        raise KeyError(product_id)

    monkeypatch.setattr(scanner, "update_dashboard_product", fake_update_dashboard_product)

    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.put(
                "/dashboard/products/7",
                json={
                    "name": "Corrected Product",
                    "location_id": 4,
                    "qu_id_stock": 7,
                    "qu_id_purchase": 7,
                    "qu_factor_purchase_to_stock": 1,
                },
            )

    response = run(request())

    assert response.status_code == 404
    assert response.json() == {"detail": "Dashboard product not found"}


def test_dashboard_edit_product_maps_grocy_errors_to_502(monkeypatch) -> None:
    async def fake_update_dashboard_product(product_id, payload):
        raise GrocyError("Grocy returned non-JSON response: setup is missing")

    monkeypatch.setattr(scanner, "update_dashboard_product", fake_update_dashboard_product)

    try:
        run(
            dashboard_edit_product(
                7,
                DashboardProductUpdate(
                    name="Corrected Product",
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 502
        assert "setup is missing" in exc.detail
    else:
        raise AssertionError("GrocyError was not converted to a 502 API error")
