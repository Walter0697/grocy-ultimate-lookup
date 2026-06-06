from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    ConfirmedProduct,
    ConfirmedProductRequest,
    LookupResponse,
    PendingProductConfirmation,
    ScanEventRequest,
)
from app.orchestrator import LookupOrchestrator
from app.scanner_service import ScannerService

app = FastAPI(title="Grocy Ultimate Lookup", version="0.1.0")
orchestrator = LookupOrchestrator()
scanner = ScannerService(lookup=orchestrator)
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(static_path / "index.html")


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


@app.get("/scan-preview/{barcode}")
async def preview_scan(barcode: str) -> dict:
    return await scanner.preview(barcode)


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
    return await scanner.products()


@app.get("/dashboard/options")
async def dashboard_options() -> dict:
    return await scanner.options()
