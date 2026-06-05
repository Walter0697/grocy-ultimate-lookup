from pydantic import BaseModel, Field, HttpUrl


class LookupResult(BaseModel):
    barcode: str
    name: str
    name_language: str | None = None
    name_origin: str | None = None
    alternate_names: dict[str, str] = Field(default_factory=dict)
    raw_name: str | None = None
    normalized_name: str | None = None
    brand: str | None = None
    quantity: str | None = None
    size: str | None = None
    count: int | None = None
    variant: str | None = None
    image_url: HttpUrl | None = None
    source: str
    confidence: float = Field(ge=0, le=1)
    match_reason: str | None = None
    match_warnings: list[str] = Field(default_factory=list)
    raw_url: HttpUrl | None = None
    raw_payload: dict | None = None


class LookupResponse(BaseModel):
    barcode: str
    found: bool
    result: LookupResult | None = None
    candidates: list[LookupResult] = Field(default_factory=list)
    research_status: str | None = None


class ConfirmedProductRequest(BaseModel):
    name: str = Field(min_length=1)
    brand: str | None = None
    quantity: str | None = None
    size: str | None = None
    count: int | None = Field(default=None, ge=1)
    variant: str | None = None
    image_url: HttpUrl | None = None
    notes: str | None = None


class ConfirmedProduct(BaseModel):
    barcode: str
    user_product_name: str
    brand: str | None = None
    quantity: str | None = None
    size: str | None = None
    count: int | None = None
    variant: str | None = None
    image_url: HttpUrl | None = None
    notes: str | None = None
    created_at: str
    updated_at: str
