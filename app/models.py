from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


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


class ScanEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    barcode: str = Field(min_length=1, max_length=120)
    mode: Literal["add", "remove", "set"]
    quantity: float = Field(ge=0)
    location_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_quantity_for_mode(self):
        if self.mode in {"add", "remove"} and self.quantity <= 0:
            raise ValueError("Add and remove quantities must be greater than zero")
        return self


class DeviceScanRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    barcode: str = Field(min_length=1, max_length=120)
    mode: Literal["add", "remove", "set"] = "add"
    quantity: float = Field(default=1, ge=0)
    location_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_quantity_for_mode(self):
        if self.mode in {"add", "remove"} and self.quantity <= 0:
            raise ValueError("Add and remove quantities must be greater than zero")
        return self


class DeviceScanResponse(BaseModel):
    event_id: str
    status: str
    barcode: str
    mode: str
    quantity: float
    product_name: str | None = None
    stock_before: float | None = None
    stock_after: float | None = None
    needs_review: bool
    message: str


class DashboardScanConfirmation(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=120)
    barcode: str = Field(min_length=1, max_length=120)
    mode: Literal["add", "remove", "set"]
    quantity: float = Field(ge=0)
    location_id: int | None = Field(default=None, gt=0)
    product: "PendingProductConfirmation"

    @model_validator(mode="after")
    def validate_quantity_for_mode(self):
        if self.mode in {"add", "remove"} and self.quantity <= 0:
            raise ValueError("Add and remove quantities must be greater than zero")
        return self


class DeviceHeartbeatRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    mode: Literal["add", "remove", "set"] | None = None
    quantity: float | None = Field(default=None, ge=0)
    location_id: int | None = Field(default=None, gt=0)
    location_name: str | None = None
    version: str | None = Field(default=None, max_length=120)


class DeviceStatus(BaseModel):
    device_id: str
    online: bool
    last_seen: str
    mode: str | None = None
    quantity: float | None = None
    location_id: int | None = None
    location_name: str | None = None
    version: str | None = None


class PendingProductConfirmation(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    brand: str | None = None
    quantity: str | None = None
    image_url: HttpUrl | None = None
    lookup_source: str | None = None
    catalog_contribution: bool = False
    location_id: int = Field(gt=0)
    qu_id_stock: int = Field(gt=0)
    qu_id_purchase: int = Field(gt=0)
    qu_factor_purchase_to_stock: float = Field(default=1, gt=0)


class DashboardProductUpdate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    brand: str | None = None
    quantity: str | None = None
    image_url: HttpUrl | None = None
    location_id: int = Field(gt=0)
    qu_id_stock: int = Field(gt=0)
    qu_id_purchase: int = Field(gt=0)
    qu_factor_purchase_to_stock: float = Field(default=1, gt=0)
