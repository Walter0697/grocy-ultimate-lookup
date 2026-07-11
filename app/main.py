from pathlib import Path
import shutil
import tomllib
from uuid import uuid4
from importlib.metadata import PackageNotFoundError, version as package_version

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.app_settings import (
    AppSettingsStore,
    CommunityCatalogDiff,
    CommunityCatalogMetadata,
    CommunityCatalogPendingProducts,
    CommunityCatalogProductSelection,
    CommunityCatalogSource,
    CommunityCatalogSourceList,
    CommunityCatalogSettingsResponse,
    CommunityCatalogSettingsUpdate,
    CommunityCatalogStatus,
    LookupSettingsResponse,
    LookupSettingsUpdate,
    public_community_catalog_settings,
    public_lookup_settings,
)
from app.config import settings
from app.community_catalog import CommunityCatalogSourceRegistry, RuntimeCommunityCatalogExporter, exporter_from_settings
from app.grocy import GrocyError
from app.grocy_units import seed_units
from app.manual_category_store import ManualCategoryStore
from app.models import (
    ConfirmedProduct,
    ConfirmedProductRequest,
    DashboardProductUpdate,
    DashboardProductEditResult,
    DashboardScanConfirmation,
    DeviceHeartbeatRequest,
    DeviceScanRequest,
    DeviceScanResponse,
    DeviceStatus,
    LookupResponse,
    ManualCategory,
    ManualCategoryCreate,
    ManualCategoryItem,
    ManualCategoryItemCreate,
    PendingProductConfirmation,
    ProductEditHistoryBarcodeListResponse,
    ProductEditHistoryDetailResponse,
    ProductEditHistoryEntry,
    ProductEditHistoryListResponse,
    ScanEventRequest,
)
from app.orchestrator import LookupOrchestrator
from app.scanner_devices import ScannerDeviceRegistry, expected_device_token
from app.scanner_service import ScannerService


def get_app_version() -> str:
    try:
        return package_version("grocy-ultimate-lookup")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text())
        return str(data["project"]["version"])


app = FastAPI(title="Grocy Ultimate Lookup", version=get_app_version())
app_settings_store = AppSettingsStore(settings.app_settings_path)
community_catalog_runtime = RuntimeCommunityCatalogExporter(app_settings_store)
catalog_source_registry = CommunityCatalogSourceRegistry(app_settings_store)
orchestrator = LookupOrchestrator(settings_store=app_settings_store)
scanner = ScannerService(lookup=orchestrator)
scanner_devices = ScannerDeviceRegistry()
manual_category_store = ManualCategoryStore(settings.manual_categories_path)
static_path = Path(__file__).parent / "static"
uploaded_images_path = Path(settings.uploaded_images_path)
uploaded_images_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")
app.mount("/uploaded-images", StaticFiles(directory=uploaded_images_path), name="uploaded-images")


@app.get("/", include_in_schema=False)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(
        versioned_index_html(),
        headers={"Cache-Control": "no-store"},
    )


def versioned_index_html() -> str:
    html = (static_path / "index.html").read_text()
    for asset in ("styles.css", "scan-dialog.css", "stock-confirm.js", "app.js"):
        version = str(int((static_path / asset).stat().st_mtime))
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    html = html.replace("{{APP_VERSION_BADGE}}", render_app_version_badge())
    return html


@app.get("/logs", include_in_schema=False)
async def logs_page() -> HTMLResponse:
    return HTMLResponse(
        versioned_logs_html(),
        headers={"Cache-Control": "no-store"},
    )


def versioned_logs_html() -> str:
    html = (static_path / "logs.html").read_text()
    for asset in ("styles.css", "logs.js"):
        version = str(int((static_path / asset).stat().st_mtime))
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    html = html.replace("{{APP_VERSION_BADGE}}", render_app_version_badge())
    return html


@app.get("/items", include_in_schema=False)
async def items_page() -> HTMLResponse:
    return HTMLResponse(
        versioned_items_html(),
        headers={"Cache-Control": "no-store"},
    )


def versioned_items_html() -> str:
    html = (static_path / "items.html").read_text()
    for asset in ("styles.css", "scan-dialog.css", "stock-confirm.js", "items-reference.json", "items.js"):
        version = str(int((static_path / asset).stat().st_mtime))
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    html = html.replace("{{APP_VERSION_BADGE}}", render_app_version_badge())
    return html


@app.get("/settings", include_in_schema=False)
async def settings_page() -> HTMLResponse:
    return HTMLResponse(
        settings_page_html(),
        headers={"Cache-Control": "no-store"},
    )


def settings_page_html() -> str:
    html = (static_path / "settings.html").read_text()
    for asset in ("styles.css", "settings.css", "vendor/sortable.min.js", "settings.js"):
        version = str(int((static_path / asset).stat().st_mtime))
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
    html = html.replace("{{APP_VERSION_BADGE}}", render_app_version_badge())
    return html


def render_app_version_badge() -> str:
    return f'<div class="app-version-badge">v{get_app_version()}</div>'


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/lookup/{barcode}", response_model=LookupResponse)
async def lookup_barcode(barcode: str, use_cache: bool = Query(default=True)) -> LookupResponse:
    return await orchestrator.lookup(barcode, use_cache=use_cache)


@app.get("/local-products/{barcode}", response_model=ConfirmedProduct)
async def get_local_product(barcode: str) -> ConfirmedProduct:
    product = orchestrator.get_confirmed_product(barcode)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local product not found")
    return product


@app.put("/local-products/{barcode}", response_model=ConfirmedProduct)
async def put_local_product(barcode: str, product: ConfirmedProductRequest) -> ConfirmedProduct:
    return orchestrator.confirm_product(barcode, product)


@app.delete("/local-products/{barcode}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_local_product(barcode: str) -> None:
    deleted = orchestrator.delete_confirmed_product(barcode)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local product not found")


@app.get("/settings/community-catalog", response_model=CommunityCatalogSettingsResponse)
async def get_community_catalog_settings() -> CommunityCatalogSettingsResponse:
    return public_community_catalog_settings(app_settings_store.get_community_catalog())


@app.put("/settings/community-catalog", response_model=CommunityCatalogSettingsResponse)
async def put_community_catalog_settings(product: CommunityCatalogSettingsUpdate) -> CommunityCatalogSettingsResponse:
    return public_community_catalog_settings(app_settings_store.update_community_catalog(product))


@app.get("/settings/community-catalog/metadata", response_model=CommunityCatalogMetadata)
async def get_community_catalog_metadata() -> CommunityCatalogMetadata:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        return CommunityCatalogMetadata()
    exporter = exporter_from_settings(current)
    warnings = exporter.sync_checkout()
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return exporter.read_catalog_metadata()


@app.put("/settings/community-catalog/metadata", response_model=CommunityCatalogMetadata)
async def put_community_catalog_metadata(metadata: CommunityCatalogMetadata) -> CommunityCatalogMetadata:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    exporter = exporter_from_settings(current)
    warnings = exporter.sync_checkout()
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    if exporter.write_catalog_metadata(metadata):
        warnings = exporter.commit_and_push_paths(["catalog.json"], "Update catalog metadata")
        if warnings:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return exporter.read_catalog_metadata()


@app.get("/settings/lookup", response_model=LookupSettingsResponse)
async def get_lookup_settings() -> LookupSettingsResponse:
    return public_lookup_settings(app_settings_store.get_lookup())


@app.put("/settings/lookup", response_model=LookupSettingsResponse)
async def put_lookup_settings(product: LookupSettingsUpdate) -> LookupSettingsResponse:
    return public_lookup_settings(app_settings_store.update_lookup(product))


@app.get("/settings/agent-search")
async def get_agent_search_availability() -> dict[str, bool | str]:
    auth_available = Path(settings.agent_search_auth_path).exists()
    codex_available = shutil.which("codex") is not None
    available = settings.enable_agent_search and auth_available and codex_available
    return {
        "available": available,
        "enabled": settings.enable_agent_search,
        "status": "Codex based search is available" if available else "Codex based search is unavailable",
    }


@app.post("/settings/grocy-units/seed")
async def seed_grocy_units() -> dict:
    try:
        return await seed_units(scanner.grocy)
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.get("/settings/community-catalog-sources", response_model=CommunityCatalogSourceList)
async def get_community_catalog_sources() -> CommunityCatalogSourceList:
    return catalog_source_registry.get_sources()


@app.put("/settings/community-catalog-sources", response_model=CommunityCatalogSourceList)
async def put_community_catalog_sources(sources: CommunityCatalogSourceList) -> CommunityCatalogSourceList:
    try:
        return catalog_source_registry.validate_and_store_sources(sources)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.post("/settings/community-catalog-sources/{source_id}/refresh", response_model=CommunityCatalogSource)
async def refresh_community_catalog_source(source_id: str) -> CommunityCatalogSource:
    try:
        return catalog_source_registry.refresh_source(source_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail == "Catalog source not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail)


@app.post("/settings/community-catalog/test", response_model=CommunityCatalogStatus)
async def test_community_catalog_settings() -> CommunityCatalogStatus:
    return app_settings_store.community_catalog_status()


@app.post("/settings/community-catalog/sync", response_model=CommunityCatalogStatus)
async def sync_community_catalog_checkout() -> CommunityCatalogStatus:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    exporter = exporter_from_settings(current)
    warnings = exporter.sync_checkout()
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return app_settings_store.community_catalog_status()


@app.get("/settings/community-catalog/diff", response_model=CommunityCatalogDiff)
async def get_community_catalog_diff() -> CommunityCatalogDiff:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        return CommunityCatalogDiff(configured=False, pending_changes=False, status="Repository URL is not configured")
    try:
        pending, status_text, files = exporter_from_settings(current).pending_changes()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return CommunityCatalogDiff(configured=True, pending_changes=pending, status=status_text, files=files)


@app.get("/settings/community-catalog/pending-products", response_model=CommunityCatalogPendingProducts)
async def get_community_catalog_pending_products() -> CommunityCatalogPendingProducts:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        return CommunityCatalogPendingProducts(configured=False, pending_changes=False)
    try:
        products = community_catalog_runtime.pending_products()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return CommunityCatalogPendingProducts(
        configured=True,
        pending_changes=bool(products),
        products=products,
    )


@app.post("/settings/community-catalog/push", response_model=CommunityCatalogDiff)
async def push_community_catalog_changes() -> CommunityCatalogDiff:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    warnings = exporter_from_settings(current).push_pending_changes()
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return await get_community_catalog_diff()


@app.post("/settings/community-catalog/push-products", response_model=CommunityCatalogPendingProducts)
async def push_community_catalog_products(selection: CommunityCatalogProductSelection) -> CommunityCatalogPendingProducts:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    warnings = community_catalog_runtime.push_pending_products(selection.barcodes)
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return await get_community_catalog_pending_products()


@app.post("/settings/community-catalog/discard", response_model=CommunityCatalogDiff)
async def discard_community_catalog_changes() -> CommunityCatalogDiff:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    warnings = exporter_from_settings(current).discard_pending_changes()
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return await get_community_catalog_diff()


@app.post("/settings/community-catalog/discard-products", response_model=CommunityCatalogPendingProducts)
async def discard_community_catalog_products(selection: CommunityCatalogProductSelection) -> CommunityCatalogPendingProducts:
    current = app_settings_store.get_community_catalog()
    if not current.repository_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository URL is not configured")
    warnings = community_catalog_runtime.discard_pending_products(selection.barcodes)
    if warnings:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="; ".join(warnings))
    return await get_community_catalog_pending_products()


@app.get("/agent-search/{barcode}")
async def get_agent_search(barcode: str) -> dict:
    agent_status = orchestrator.get_agent_search_status(barcode)
    if agent_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent search not found")
    return agent_status


@app.post("/agent-search/{barcode}")
async def retry_agent_search(barcode: str) -> dict:
    agent_status = orchestrator.retry_agent_search(barcode)
    if agent_status is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent search is unavailable; check Codex CLI and auth mount",
        )
    return agent_status


@app.delete("/agent-search/{barcode}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_search(barcode: str) -> None:
    deleted = orchestrator.delete_agent_search(barcode)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent search not found")


@app.post("/scan-events")
async def create_scan_event(event: ScanEventRequest) -> dict:
    return await scanner.process(event)


@app.post("/dashboard/scan-confirm")
async def confirm_dashboard_scan(confirmation: DashboardScanConfirmation) -> dict:
    try:
        return await scanner.confirm_dashboard_scan(confirmation)
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


async def save_uploaded_product_image(file: UploadFile) -> dict[str, str]:
    allowed_extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    suffix = allowed_extensions.get(content_type)
    if suffix is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload must be a JPEG, PNG, WebP, or GIF image")

    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image upload must be 8 MB or smaller")

    file_name = f"{uuid4().hex}{suffix}"
    target = uploaded_images_path / file_name
    target.write_bytes(content)
    return {
        "image_url": f"{settings.uploaded_images_base_url.rstrip('/')}/{file_name}",
        "preview_url": f"/uploaded-images/{file_name}",
    }


@app.post("/product-image-uploads")
async def upload_product_image(file: UploadFile = File(...)) -> dict[str, str]:
    return await save_uploaded_product_image(file)


@app.post("/dashboard/products/{product_id}/request-image-review")
async def dashboard_request_image_review(product_id: int) -> dict:
    try:
        return await scanner.request_image_review(product_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard product not found")
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.post("/scan-events/{event_id}/image")
async def attach_scan_event_image(event_id: str, file: UploadFile = File(...)) -> dict:
    uploaded = await save_uploaded_product_image(file)
    try:
        return await scanner.attach_image_to_event(event_id, uploaded["image_url"])
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.get("/external/scan-events")
async def external_list_scan_events(
    event_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    x_gul_api_key: str | None = Header(default=None),
) -> list[dict]:
    require_gul_api_key(x_gul_api_key)
    return scanner.store.list(status=event_status, limit=limit)


@app.get("/external/scan-events/{event_id}")
async def external_get_scan_event(event_id: str, x_gul_api_key: str | None = Header(default=None)) -> dict:
    require_gul_api_key(x_gul_api_key)
    event = scanner.store.get(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")
    return event


@app.post("/external/scan-events/{event_id}/image")
async def external_attach_scan_event_image(
    event_id: str,
    file: UploadFile = File(...),
    x_gul_api_key: str | None = Header(default=None),
) -> dict:
    require_gul_api_key(x_gul_api_key)
    return await attach_scan_event_image(event_id, file)


@app.get("/external/dashboard/products")
async def external_dashboard_products(x_gul_api_key: str | None = Header(default=None)) -> list[dict]:
    require_gul_api_key(x_gul_api_key)
    return await dashboard_products()


@app.post("/external/dashboard/products/{product_id}/request-image-review")
async def external_dashboard_request_image_review(
    product_id: int,
    x_gul_api_key: str | None = Header(default=None),
) -> dict:
    require_gul_api_key(x_gul_api_key)
    return await dashboard_request_image_review(product_id)


@app.post("/scanner/scan", response_model=DeviceScanResponse)
async def create_device_scan(
    event: DeviceScanRequest,
    x_scanner_token: str | None = Header(default=None),
) -> DeviceScanResponse:
    require_scanner_token(event.device_id, x_scanner_token)
    return await scanner.process_device_scan(event)


@app.post("/scanner/heartbeat", response_model=DeviceStatus)
async def scanner_heartbeat(
    heartbeat: DeviceHeartbeatRequest,
    x_scanner_token: str | None = Header(default=None),
) -> DeviceStatus:
    require_scanner_token(heartbeat.device_id, x_scanner_token)
    return scanner_devices.heartbeat(heartbeat)


@app.get("/scanner/devices", response_model=list[DeviceStatus])
async def list_scanner_devices() -> list[DeviceStatus]:
    return scanner_devices.list()


def require_scanner_token(device_id: str, token: str | None) -> None:
    expected = expected_device_token(device_id)
    if expected is None:
        return
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Scanner token is required")
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid scanner token")


def require_gul_api_key(api_key: str | None) -> None:
    expected = settings.gul_api_key
    if not expected:
        return
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GUL API key is required")
    if api_key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid GUL API key")


@app.get("/scan-preview/{barcode}")
async def preview_scan(barcode: str) -> dict:
    try:
        return await scanner.preview(barcode)
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.get("/scan-events")
async def list_scan_events(
    event_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    return scanner.store.list(status=event_status, limit=limit)


@app.get("/scan-events/{event_id}")
async def get_scan_event(event_id: str) -> dict:
    event = scanner.store.get(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")
    return event


@app.delete("/scan-events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan_event(event_id: str) -> None:
    deleted = scanner.store.delete(event_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")


@app.post("/scan-events/{event_id}/refresh")
async def refresh_scan_event(event_id: str) -> dict:
    try:
        return await scanner.refresh(event_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")


@app.post("/scan-events/{event_id}/confirm")
async def confirm_scan_event(event_id: str, product: PendingProductConfirmation) -> dict:
    try:
        return await scanner.confirm(event_id, product)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan event not found")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.get("/dashboard/products")
async def dashboard_products() -> list[dict]:
    try:
        return await scanner.products()
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.put("/dashboard/products/{product_id}", response_model=DashboardProductEditResult)
async def dashboard_edit_product(product_id: int, product: DashboardProductUpdate) -> DashboardProductEditResult:
    try:
        result = await scanner.update_dashboard_product(product_id, product)
        return DashboardProductEditResult.model_validate(result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard product not found")
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@app.get("/product-edit-history", response_model=ProductEditHistoryListResponse)
async def product_edit_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="created_at"),
    order: str = Query(default="desc"),
    query: str = Query(default=""),
) -> ProductEditHistoryListResponse:
    try:
        return scanner.history_store.list(limit=limit, offset=offset, sort=sort, order=order, query=query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.get("/product-edit-history/barcodes", response_model=ProductEditHistoryBarcodeListResponse)
async def product_edit_history_barcodes(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="last_edited_at"),
    order: str = Query(default="desc"),
    query: str = Query(default=""),
) -> ProductEditHistoryBarcodeListResponse:
    try:
        return scanner.history_store.barcode_summary(limit=limit, offset=offset, sort=sort, order=order, query=query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@app.get("/product-edit-history/{history_id}", response_model=ProductEditHistoryDetailResponse)
async def product_edit_history_detail(history_id: int) -> ProductEditHistoryDetailResponse:
    detail = scanner.history_store.detail(history_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product edit history not found")
    return detail


@app.get("/dashboard/manual-categories", response_model=list[ManualCategory])
async def list_manual_categories() -> list[ManualCategory]:
    return manual_category_store.list_categories()


@app.post("/dashboard/manual-categories", response_model=ManualCategory)
async def create_manual_category(category: ManualCategoryCreate) -> ManualCategory:
    return manual_category_store.create_category(
        name=category.name,
        group=category.group,
        emoji=category.emoji,
        image_url=category.image_url,
    )


@app.get("/dashboard/manual-category-items", response_model=list[ManualCategoryItem])
async def list_manual_category_items(
    category_id: str | None = Query(default=None),
) -> list[ManualCategoryItem]:
    return manual_category_store.list_items(category_id)


@app.post("/dashboard/manual-categories/{category_id}/items", response_model=ManualCategoryItem)
async def create_manual_category_item(
    category_id: str,
    item: ManualCategoryItemCreate,
) -> ManualCategoryItem:
    return manual_category_store.create_item(
        category_id=category_id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        default_location=item.default_location,
        note=item.note,
        emoji=item.emoji,
        image_url=item.image_url,
        favorite=item.favorite,
    )


@app.get("/dashboard/options")
async def dashboard_options() -> dict:
    try:
        options = await scanner.options()
    except GrocyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    options["scanner_devices"] = [device.model_dump(mode="json") for device in scanner_devices.list()]
    return options
