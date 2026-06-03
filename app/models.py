from pydantic import BaseModel, Field, HttpUrl


class LookupResult(BaseModel):
    barcode: str
    name: str
    brand: str | None = None
    quantity: str | None = None
    image_url: HttpUrl | None = None
    source: str
    confidence: float = Field(ge=0, le=1)
    raw_url: HttpUrl | None = None


class LookupResponse(BaseModel):
    barcode: str
    found: bool
    result: LookupResult | None = None
    candidates: list[LookupResult] = Field(default_factory=list)
