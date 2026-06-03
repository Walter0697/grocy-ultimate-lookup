from fastapi import FastAPI, Query

from app.models import LookupResponse
from app.orchestrator import LookupOrchestrator

app = FastAPI(title="Grocy Ultimate Lookup", version="0.1.0")
orchestrator = LookupOrchestrator()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/lookup/{barcode}", response_model=LookupResponse)
async def lookup_barcode(barcode: str, use_cache: bool = Query(default=True)) -> LookupResponse:
    return await orchestrator.lookup(barcode, use_cache=use_cache)
