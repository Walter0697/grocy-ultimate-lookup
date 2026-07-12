from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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


class CatalogImageReviewRequest(BaseModel):
    barcode: str = Field(min_length=1, max_length=120)
    product_name: str = Field(min_length=1, max_length=120)
    variant_id: str = Field(min_length=1, max_length=120)
    location_id: int | None = Field(default=None, gt=0)


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


class DashboardProductEditProductSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    name: str
    image_url: HttpUrl | None = None
    stock_amount: float | None = None
    editable: bool = True


class ProductEditHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    product_id: int
    barcode: str
    source: str
    changed_fields: list[str]
    before: dict[str, object]
    after: dict[str, object]
    related_event_id: str | None = None
    created_at: str


class ProductEditHistoryDiffField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    before: object | None = None
    after: object | None = None


class ProductEditHistoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: ProductEditHistoryEntry
    diffs: list[ProductEditHistoryDiffField]


class ProductEditHistoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductEditHistoryEntry]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    sort: Literal["created_at", "product_name", "barcode", "product_id"]
    order: Literal["asc", "desc"]
    query: str = ""


class ProductEditHistoryBarcodeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    product_name: str
    latest_product_id: int
    edit_count: int = Field(ge=0)
    last_edited_at: str


class ProductEditHistoryBarcodeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductEditHistoryBarcodeSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    sort: Literal["barcode", "product_name", "edit_count", "last_edited_at"]
    order: Literal["asc", "desc"]
    query: str = ""


class ScanEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, object | None]]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    filter: Literal["all", "review", "applied", "failed"] = "all"
    counts: dict[str, int] = Field(default_factory=dict)


class DashboardProductEditResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: DashboardProductEditProductSummary
    updated_event_count: int = 0
    history_entry: ProductEditHistoryEntry | None = None


class ManualCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    group: Literal["produce", "fridge", "dry", "bakery", "other"] = "other"
    emoji: str | None = Field(default=None, max_length=16)
    image_url: str | None = None

    @model_validator(mode="after")
    def validate_icon(self) -> "ManualCategoryCreate":
        emoji = (self.emoji or "").strip() or None
        image_url = (self.image_url or "").strip() or None
        self.emoji = emoji
        self.image_url = image_url
        if not emoji and not image_url:
            raise ValueError("Choose an emoji or upload an image for the category icon")
        if emoji and image_url:
            raise ValueError("Use either an emoji or an image, not both")
        return self


class ManualCategory(ManualCategoryCreate):
    id: str
    custom: bool = True
    variants: list[dict] = Field(default_factory=list)


class ManualCategoryItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=40)
    default_location: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=240)
    emoji: str | None = Field(default=None, max_length=16)
    image_url: str | None = None
    favorite: bool = False

    @model_validator(mode="after")
    def validate_icon(self) -> "ManualCategoryItemCreate":
        emoji = (self.emoji or "").strip() or None
        image_url = (self.image_url or "").strip() or None
        note = (self.note or "").strip() or None
        self.emoji = emoji
        self.image_url = image_url
        self.note = note
        if emoji and image_url:
            raise ValueError("Use either an emoji or a lookup photo for the item, not both")
        if image_url and not image_url.startswith("/uploaded-images/"):
            raise ValueError("Item photos must be uploaded through lookup")
        return self


class ManualCategoryItem(ManualCategoryItemCreate):
    id: str
    category_id: str
    custom: bool = True
