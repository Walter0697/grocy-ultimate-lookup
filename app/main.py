from fastapi import FastAPI, HTTPException, Query, status

from app.models import ConfirmedProduct, ConfirmedProductRequest, LookupResponse
from app.orchestrator import LookupOrchestrator

app = FastAPI(title="Grocy Ultimate Lookup", version="0.1.0")
orchestrator = LookupOrchestrator()


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
