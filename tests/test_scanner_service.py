import asyncio
from types import SimpleNamespace

import pytest

from app.models import (
    DashboardProductEditResult,
    DashboardProductEditProductSummary,
    DashboardProductUpdate,
    DashboardScanConfirmation,
    DeviceScanRequest,
    LookupResponse,
    LookupResult,
    ProductEditHistoryBarcodeListResponse,
    ProductEditHistoryDetailResponse,
    ProductEditHistoryDiffField,
    ProductEditHistoryEntry,
    PendingProductConfirmation,
    ScanEventRequest,
)
from app.auto_created_store import AutoCreatedProductStore
from app.local_store import LocalProductStore
from app.product_edit_history import ProductEditHistoryStore
from app.scan_events import ScanEventStore
from app.scanner_service import ScannerService


class FakeCommunityCatalog:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.exported = []

    def export_confirmed_product(self, barcode, product, *, result_source=None):
        if self.error:
            raise self.error
        self.exported.append((barcode, product, result_source))
        return SimpleNamespace(warnings=())


class FakeLookup:
    def __init__(self, response: LookupResponse) -> None:
        self.response = response
        self.calls = []

    async def lookup(self, barcode: str, use_cache: bool = False) -> LookupResponse:
        self.calls.append((barcode, use_cache))
        return self.response


class FailingAutoCreatedStore:
    def upsert(self, *, product_id: int, barcode: str, source: str) -> None:
        raise RuntimeError("ownership store write failed")


class ReadFailingAutoCreatedStore:
    def get_by_product_id(self, product_id: int):
        raise RuntimeError("ownership store read failed")


class FailingHistoryStore:
    def create(self, **kwargs):
        raise RuntimeError("history write failed")


class FakeGrocy:
    def __init__(self, product=None, fail_apply: Exception | None = None) -> None:
        self.product = product
        self.fail_apply = fail_apply
        self.operations = []
        self.created = []
        self.updated = []

    async def find_product_by_barcode(self, barcode: str):
        return self.product

    async def get_product_barcode(self, product_id: int):
        if self.product is None or int(self.product["product"]["id"]) != product_id:
            return None
        return "123456"

    async def apply_stock_operation(self, product_id: int, event: ScanEventRequest):
        self.operations.append((product_id, event))
        if self.fail_apply:
            raise self.fail_apply
        name = self.product["product"]["name"]
        self.product = details(product_id, name, event.quantity if event.mode == "set" else 3)
        return self.product

    async def create_product(self, barcode: str, product: PendingProductConfirmation):
        self.created.append((barcode, product))
        self.product = details(22, product.name, 0)
        return self.product

    async def update_product(self, product_id: int, barcode: str, product: PendingProductConfirmation):
        self.updated.append((product_id, barcode, product))
        self.product = details(product_id, product.name, 0)
        return self.product

    async def get_objects(self, entity: str):
        if entity == "locations":
            return [{"id": 4, "name": "Kitchen"}]
        if entity == "quantity_units":
            return [{"id": 7, "name": "Piece"}]
        return []

    async def dashboard_products(self):
        return [self.product_card(self.product)] if self.product is not None else []

    def product_card(self, product):
        return {
            "product_id": product["product"]["id"],
            "name": product["product"]["name"],
            "image_url": None,
            "stock_amount": product["stock_amount"],
        }


def details(product_id: int = 7, name: str = "Known Product", stock: float = 2):
    return {"product": {"id": product_id, "name": name}, "stock_amount": stock}


def editable_details(
    product_id: int = 7,
    name: str = "Known Product",
    *,
    description: str | None = "Original description",
    brand: str | None = "Original brand",
    quantity: str | None = "1 bag",
    image_url: str | None = "https://old.example/product.jpg",
    location_id: int = 2,
    qu_id_stock: int = 7,
    qu_id_purchase: int = 7,
    qu_factor_purchase_to_stock: float = 1,
    stock: float = 2,
):
    return {
        "product": {
            "id": product_id,
            "name": name,
            "description": description,
            "brand": brand,
            "quantity": quantity,
            "location_id": location_id,
            "qu_id_stock": qu_id_stock,
            "qu_id_purchase": qu_id_purchase,
            "qu_factor_purchase_to_stock": qu_factor_purchase_to_stock,
        },
        "stock_amount": stock,
        "image_url": image_url,
    }


class EditableGrocy(FakeGrocy):
    def __init__(self, product=None) -> None:
        super().__init__(product or editable_details())

    async def update_product(self, product_id: int, barcode: str, product: PendingProductConfirmation):
        self.updated.append((product_id, barcode, product))
        self.product = editable_details(
            product_id=product_id,
            name=product.name,
            description=product.description,
            brand=product.brand,
            quantity=product.quantity,
            image_url=str(product.image_url) if product.image_url else None,
            location_id=product.location_id,
            qu_id_stock=product.qu_id_stock,
            qu_id_purchase=product.qu_id_purchase,
            qu_factor_purchase_to_stock=product.qu_factor_purchase_to_stock,
            stock=self.product.get("stock_amount", 0),
        )
        return self.product

    def product_card(self, product):
        return {
            "product_id": product["product"]["id"],
            "name": product["product"]["name"],
            "description": product["product"].get("description"),
            "location_id": product["product"].get("location_id"),
            "qu_id_purchase": product["product"].get("qu_id_purchase"),
            "qu_id_stock": product["product"].get("qu_id_stock"),
            "image_url": product.get("image_url"),
            "stock_amount": product["stock_amount"],
            "editable": True,
        }


class PreserveImageGrocy(EditableGrocy):
    async def update_product(self, product_id: int, barcode: str, product: PendingProductConfirmation):
        self.updated.append((product_id, barcode, product))
        self.product = editable_details(
            product_id=product_id,
            name=product.name,
            description=product.description,
            brand=product.brand,
            quantity=product.quantity,
            image_url=self.product.get("image_url"),
            location_id=product.location_id,
            qu_id_stock=product.qu_id_stock,
            qu_id_purchase=product.qu_id_purchase,
            qu_factor_purchase_to_stock=product.qu_factor_purchase_to_stock,
            stock=self.product.get("stock_amount", 0),
        )
        return self.product


def request(event_id="event-1"):
    return ScanEventRequest(
        event_id=event_id,
        device_id="kitchen-pi",
        barcode="123456",
        mode="add",
        quantity=1,
        location_id=2,
    )


def service(tmp_path, grocy, lookup, community_catalog=None):
    scanner = ScannerService(
        store=ScanEventStore(str(tmp_path / "events.sqlite3")),
        grocy=grocy,
        lookup=lookup,
        local_store=LocalProductStore(str(tmp_path / "local.sqlite3")),
        auto_created_store=AutoCreatedProductStore(str(tmp_path / "auto-created.sqlite3")),
        community_catalog=community_catalog,
    )
    return scanner


def run(coro):
    return asyncio.run(coro)


def test_known_grocy_product_is_applied_before_external_lookup(tmp_path) -> None:
    grocy = FakeGrocy(details())
    lookup = FakeLookup(LookupResponse(barcode="123456", found=False))
    scanner = service(tmp_path, grocy, lookup)

    result = run(scanner.process(request()))

    assert result["status"] == "applied"
    assert result["stock_before"] == 2
    assert result["stock_after"] == 3
    assert lookup.calls == []
    assert len(grocy.operations) == 1
    assert grocy.operations[0][1].location_id == 2


def test_device_scan_generates_event_id_and_returns_compact_response(tmp_path) -> None:
    grocy = FakeGrocy(details())
    lookup = FakeLookup(LookupResponse(barcode="123456", found=False))
    scanner = service(tmp_path, grocy, lookup)

    result = run(
        scanner.process_device_scan(
            DeviceScanRequest(device_id="kitchen-pi", barcode="123456", mode="add", quantity=2, location_id=2)
        )
    )

    assert result["event_id"].startswith("kitchen-pi-")
    assert result["status"] == "applied"
    assert result["barcode"] == "123456"
    assert result["product_name"] == "Known Product"
    assert result["stock_after"] == 3
    assert len(grocy.operations) == 1


def test_preview_checks_grocy_before_lookup(tmp_path) -> None:
    grocy = FakeGrocy(details())
    lookup = FakeLookup(LookupResponse(barcode="123456", found=False))
    scanner = service(tmp_path, grocy, lookup)

    preview = run(scanner.preview("123456"))

    assert preview["resolution"] == "grocy"
    assert preview["product"]["name"] == "Known Product"
    assert lookup.calls == []


def test_dashboard_products_marks_products_as_editable(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    products = run(scanner.products())

    assert products == [
        {
            "product_id": 7,
            "name": "Known Product",
            "image_url": None,
            "stock_amount": 2,
            "editable": True,
        }
    ]


def test_dashboard_products_preserves_malformed_product_id_from_grocy_card(tmp_path) -> None:
    grocy = FakeGrocy({"product": {"id": "broken", "name": "Known Product"}, "stock_amount": 2})
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    products = run(scanner.products())

    assert products == [
        {
            "product_id": "broken",
            "name": "Known Product",
            "image_url": None,
            "stock_amount": 2,
            "editable": True,
        }
    ]


def test_edit_dashboard_product_updates_existing_grocy_product(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    updated = run(
        scanner.update_dashboard_product(
            7,
            DashboardProductUpdate(
                name="Corrected Product",
                description="Fixed details",
                brand="Brand",
                quantity="1 box",
                image_url=None,
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    assert updated["product"] == {
        "product_id": 7,
        "name": "Corrected Product",
        "image_url": None,
        "stock_amount": 0,
        "editable": True,
    }
    assert updated["updated_event_count"] == 0
    assert updated["history_entry"]["source"] == "dashboard"
    assert grocy.updated[0][0] == 7
    assert grocy.updated[0][1] == "123456"
    assert grocy.updated[0][2].description == "Fixed details"


def test_edit_dashboard_product_returns_backfill_summary(tmp_path) -> None:
    grocy = EditableGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    scanner.store.create(
        ScanEventRequest(
            event_id="applied-owned",
            device_id="kitchen-pi",
            barcode="000000",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "applied-owned",
        status="applied",
        product_id=7,
        product_name="Known Product",
        image_url="https://old.example/product.jpg",
        stock_before=2,
        stock_after=3,
    )
    scanner.store.create(
        ScanEventRequest(
            event_id="applied-barcode-fallback",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "applied-barcode-fallback",
        status="applied",
        product_id=None,
        product_name="Known Product",
        image_url="https://old.example/product.jpg",
        stock_before=4,
        stock_after=5,
    )

    result = run(
        scanner.update_dashboard_product(
            7,
            DashboardProductUpdate(
                name="Corrected Product",
                description="Fixed details",
                brand="Brand",
                quantity="1 box",
                image_url=None,
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    validated = DashboardProductEditResult.model_validate(result)
    applied_owned = scanner.store.get("applied-owned")
    applied_barcode_fallback = scanner.store.get("applied-barcode-fallback")

    assert isinstance(validated.product, DashboardProductEditProductSummary)
    assert isinstance(validated.history_entry, ProductEditHistoryEntry)
    assert validated.product.product_id == 7
    assert validated.product.name == "Corrected Product"
    assert validated.product.editable is True
    assert validated.product.image_url is None
    assert validated.updated_event_count == 2
    assert validated.history_entry.id > 0
    assert validated.history_entry.product_id == 7
    assert validated.history_entry.barcode == "123456"
    assert validated.history_entry.source == "dashboard"
    assert validated.history_entry.changed_fields == [
        "brand",
        "description",
        "image_url",
        "location_id",
        "name",
        "quantity",
    ]
    assert validated.history_entry.before == {
        "brand": "Original brand",
        "description": "Original description",
        "image_url": "https://old.example/product.jpg",
        "location_id": 2,
        "name": "Known Product",
        "quantity": "1 bag",
    }
    assert validated.history_entry.after == {
        "brand": "Brand",
        "description": "Fixed details",
        "image_url": None,
        "location_id": 4,
        "name": "Corrected Product",
        "quantity": "1 box",
    }
    assert validated.history_entry.related_event_id is None
    assert validated.history_entry.created_at.endswith("Z")
    assert applied_owned["product_name"] == "Corrected Product"
    assert applied_owned["image_url"] is None
    assert applied_barcode_fallback["product_name"] == "Corrected Product"
    assert applied_barcode_fallback["image_url"] is None


def test_edit_dashboard_product_returns_success_when_history_write_fails(tmp_path, caplog) -> None:
    grocy = EditableGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))
    scanner.history_store = FailingHistoryStore()

    scanner.store.create(
        ScanEventRequest(
            event_id="applied-barcode-fallback",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "applied-barcode-fallback",
        status="applied",
        product_id=None,
        product_name="Known Product",
        image_url="https://old.example/product.jpg",
        stock_before=4,
        stock_after=5,
    )

    with caplog.at_level("WARNING"):
        result = run(
            scanner.update_dashboard_product(
                7,
                DashboardProductUpdate(
                    name="Corrected Product",
                    description="Fixed details",
                    brand="Brand",
                    quantity="1 box",
                    image_url=None,
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )

    validated = DashboardProductEditResult.model_validate(result)

    assert result["product"]["product_id"] == 7
    assert result["product"]["name"] == "Corrected Product"
    assert result["updated_event_count"] == 1
    assert result["history_entry"] is None
    assert validated.history_entry is None
    assert scanner.store.get("applied-barcode-fallback")["product_name"] == "Corrected Product"
    assert "history write failed" in caplog.text


def test_edit_dashboard_product_returns_success_when_backfill_fails(tmp_path, caplog) -> None:
    grocy = EditableGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    scanner.store.create(
        ScanEventRequest(
            event_id="applied-barcode-fallback",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "applied-barcode-fallback",
        status="applied",
        product_id=None,
        product_name="Known Product",
        image_url="https://old.example/product.jpg",
        stock_before=4,
        stock_after=5,
    )

    def fail_backfill(**kwargs):
        raise RuntimeError("backfill failed")

    scanner.store.backfill_product_snapshot = fail_backfill

    with caplog.at_level("WARNING"):
        result = run(
            scanner.update_dashboard_product(
                7,
                DashboardProductUpdate(
                    name="Corrected Product",
                    description="Fixed details",
                    brand="Brand",
                    quantity="1 box",
                    image_url=None,
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )

    validated = DashboardProductEditResult.model_validate(result)

    assert result["product"]["product_id"] == 7
    assert result["product"]["name"] == "Corrected Product"
    assert result["updated_event_count"] == 0
    assert result["history_entry"]["source"] == "dashboard"
    assert validated.history_entry is not None
    assert scanner.store.get("applied-barcode-fallback")["product_name"] == "Known Product"
    assert "backfill failed" in caplog.text


def test_edit_dashboard_product_skips_reupload_for_unchanged_image_url(tmp_path) -> None:
    grocy = PreserveImageGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    result = run(
        scanner.update_dashboard_product(
            7,
            DashboardProductUpdate(
                name="Corrected Product",
                description="Fixed details",
                brand="Brand",
                quantity="1 box",
                image_url="https://old.example/product.jpg",
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    validated = DashboardProductEditResult.model_validate(result)

    assert grocy.updated[0][2].image_url is None
    assert str(validated.product.image_url) == "https://old.example/product.jpg"
    assert "image_url" not in validated.history_entry.changed_fields


def test_edit_dashboard_product_does_not_rewrite_pending_or_failed_events(tmp_path) -> None:
    grocy = EditableGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    scanner.store.create(
        ScanEventRequest(
            event_id="pending-match",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "pending-match",
        status="pending",
        product_id=7,
        product_name="Pending Name",
        image_url="https://old.example/pending.jpg",
        stock_before=1,
        stock_after=2,
    )

    scanner.store.create(
        ScanEventRequest(
            event_id="failed-match",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    scanner.store.update(
        "failed-match",
        status="failed",
        product_id=7,
        product_name="Failed Name",
        image_url="https://old.example/failed.jpg",
        stock_before=3,
        stock_after=4,
        error="lookup failed",
    )

    result = run(
        scanner.update_dashboard_product(
            7,
            DashboardProductUpdate(
                name="Corrected Product",
                description="Fixed details",
                brand="Brand",
                quantity="1 box",
                image_url=None,
                location_id=4,
                qu_id_stock=7,
                qu_id_purchase=7,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    validated = DashboardProductEditResult.model_validate(result)
    pending_match = scanner.store.get("pending-match")
    failed_match = scanner.store.get("failed-match")

    assert validated.product.name == "Corrected Product"
    assert validated.updated_event_count == 0
    assert pending_match["product_name"] == "Pending Name"
    assert pending_match["image_url"] == "https://old.example/pending.jpg"
    assert failed_match["product_name"] == "Failed Name"
    assert failed_match["image_url"] == "https://old.example/failed.jpg"
    assert failed_match["error"] == "lookup failed"


def test_edit_dashboard_product_rejects_stale_owned_product(tmp_path) -> None:
    scanner = service(tmp_path, FakeGrocy(), FakeLookup(LookupResponse(barcode="123456", found=False)))
    scanner.auto_created_store.upsert(product_id=7, barcode="123456", source="open_food_facts")

    with pytest.raises(KeyError):
        run(
            scanner.update_dashboard_product(
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


def test_edit_dashboard_product_rejects_owned_product_when_barcode_points_to_other_product(tmp_path) -> None:
    scanner = service(tmp_path, FakeGrocy(details(9, "Other Product", 2)), FakeLookup(LookupResponse(barcode="123456", found=False)))
    scanner.auto_created_store.upsert(product_id=7, barcode="123456", source="open_food_facts")

    with pytest.raises(KeyError):
        run(
            scanner.update_dashboard_product(
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


def test_dashboard_preview_does_not_auto_create_trusted_lookup_product(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Lookup Product",
        image_url="https://example.test/product.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))

    preview = run(scanner.preview("123456"))

    assert preview["resolution"] == "lookup"
    assert preview["product"]["name"] == "Trusted Lookup Product"
    assert grocy.created == []


def test_preview_uses_lookup_for_unknown_grocy_barcode(tmp_path) -> None:
    result = LookupResult(barcode="123456", name="Suggested Product", source="test", confidence=0.8)
    lookup = FakeLookup(LookupResponse(barcode="123456", found=True, result=result))
    scanner = service(tmp_path, FakeGrocy(), lookup)

    preview = run(scanner.preview("123456"))

    assert preview["resolution"] == "lookup"
    assert preview["product"]["name"] == "Suggested Product"


def test_process_auto_creates_complete_trusted_lookup_result_for_scanner_path(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))

    event = run(scanner.process(request()))

    assert event["status"] == "applied"
    assert event["product_name"] == "Trusted Product"
    assert len(grocy.created) == 1
    assert grocy.created[0][1].location_id == 4
    assert grocy.created[0][1].qu_id_stock == 7
    assert grocy.created[0][1].qu_id_purchase == 7
    assert grocy.created[0][1].qu_factor_purchase_to_stock == 1
    assert len(grocy.operations) == 1


def test_process_auto_create_records_owned_product_for_dashboard_edit(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))

    run(scanner.process(request()))

    record = scanner.auto_created_store.get_by_product_id(22)
    assert record == {"product_id": 22, "barcode": "123456", "source": "open_food_facts"}


def test_process_auto_create_ignores_ownership_write_failure(tmp_path, caplog) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    scanner = ScannerService(
        store=ScanEventStore(str(tmp_path / "events.sqlite3")),
        grocy=FakeGrocy(),
        lookup=FakeLookup(LookupResponse(barcode="123456", found=True, result=result)),
        local_store=LocalProductStore(str(tmp_path / "local.sqlite3")),
        auto_created_store=FailingAutoCreatedStore(),
    )

    with caplog.at_level("WARNING"):
        event = run(scanner.process(request()))

    assert event["status"] == "applied"
    assert len(scanner.grocy.created) == 1
    assert len(scanner.grocy.operations) == 1
    assert "Auto-created product ownership write failed for 123456: ownership store write failed" in caplog.text


def test_process_auto_create_fails_on_malformed_create_payload(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )

    class MalformedCreateGrocy(FakeGrocy):
        async def create_product(self, barcode: str, product: PendingProductConfirmation):
            self.created.append((barcode, product))
            self.product = {"product": {"id": "broken", "name": product.name}, "stock_amount": 0}
            return self.product

    class BypassingApplyScannerService(ScannerService):
        async def _apply(self, request: ScanEventRequest, grocy_product: dict) -> dict:
            return {"status": "applied", "barcode": request.barcode}

    scanner = BypassingApplyScannerService(
        store=ScanEventStore(str(tmp_path / "events.sqlite3")),
        grocy=MalformedCreateGrocy(),
        lookup=FakeLookup(LookupResponse(barcode="123456", found=True, result=result)),
        local_store=LocalProductStore(str(tmp_path / "local.sqlite3")),
        auto_created_store=AutoCreatedProductStore(str(tmp_path / "auto-created.sqlite3")),
    )

    event = run(scanner.process(request()))

    assert event["status"] == "failed"
    assert "invalid literal" in event["error"]
    assert len(scanner.grocy.created) == 1
    assert len(scanner.grocy.operations) == 0


def test_catalog_lookup_auto_create_does_not_export_back_to_own_catalog(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Catalog Product",
        image_url="https://example.test/catalog-product.jpg",
        source="community_catalog",
        confidence=0.95,
    )
    catalog = FakeCommunityCatalog()
    grocy = FakeGrocy()
    scanner = service(
        tmp_path,
        grocy,
        FakeLookup(LookupResponse(barcode="123456", found=True, result=result)),
        community_catalog=catalog,
    )

    event = run(scanner.process(request()))

    assert event["status"] == "applied"
    assert event["product_name"] == "Catalog Product"
    assert len(grocy.created) == 1
    assert catalog.exported == []


def test_preview_does_not_auto_create_incomplete_or_uncertain_lookup_result(tmp_path) -> None:
    uncertain = LookupResult(
        barcode="123456",
        name="Uncertain Product",
        image_url="https://example.test/image.jpg",
        source="web_search",
        confidence=0.95,
        match_warnings=["search_title_product_name_mismatch"],
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=uncertain)))

    preview = run(scanner.preview("123456"))

    assert preview["resolution"] == "lookup"
    assert grocy.created == []


def test_duplicate_event_id_does_not_apply_stock_twice(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    first = run(scanner.process(request()))
    second = run(scanner.process(request()))

    assert first == second
    assert len(grocy.operations) == 1


def test_dashboard_confirm_uses_edited_product_before_applying_scan(tmp_path) -> None:
    catalog = FakeCommunityCatalog()
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
        community_catalog=catalog,
    )

    event = run(
        scanner.confirm_dashboard_scan(
            DashboardScanConfirmation(
                event_id="dashboard-1",
                device_id="dashboard-manual",
                barcode="123456",
                mode="add",
                quantity=2,
                location_id=4,
                product=PendingProductConfirmation(
                    name="Edited Product",
                    brand="Edited Brand",
                    quantity="12 oz",
                    image_url="http://host.docker.internal:9290/uploaded-images/edited-product.jpg",
                    catalog_contribution=True,
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=8,
                    qu_factor_purchase_to_stock=12,
                ),
            )
        )
    )

    assert event["status"] == "applied"
    assert event["product_name"] == "Edited Product"
    assert len(scanner.grocy.created) == 1
    assert scanner.grocy.created[0][1].name == "Edited Product"
    assert scanner.grocy.created[0][1].qu_id_stock == 7
    assert scanner.grocy.created[0][1].qu_id_purchase == 8
    assert scanner.grocy.created[0][1].qu_factor_purchase_to_stock == 12
    assert scanner.grocy.operations[0][1].location_id == 4
    assert catalog.exported[0][1].name == "Edited Product"
    assert (
        str(catalog.exported[0][1].image_url)
        == "http://host.docker.internal:9290/uploaded-images/edited-product.jpg"
    )


def test_dashboard_confirm_does_not_export_lookup_suggestion_to_catalog(tmp_path) -> None:
    catalog = FakeCommunityCatalog()
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
        community_catalog=catalog,
    )

    event = run(
        scanner.confirm_dashboard_scan(
            DashboardScanConfirmation(
                event_id="dashboard-lookup",
                device_id="dashboard-manual",
                barcode="123456",
                mode="add",
                quantity=1,
                product=PendingProductConfirmation(
                    name="Lookup Product",
                    brand="Lookup Brand",
                    quantity="12 oz",
                    catalog_contribution=False,
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )
    )

    assert event["status"] == "applied"
    assert catalog.exported == []


def test_dashboard_confirm_updates_existing_grocy_product_before_applying_scan(tmp_path) -> None:
    grocy = FakeGrocy(details(9, "Old Product", 1))
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    event = run(
        scanner.confirm_dashboard_scan(
            DashboardScanConfirmation(
                event_id="dashboard-existing",
                device_id="dashboard-manual",
                barcode="123456",
                mode="add",
                quantity=1,
                product=PendingProductConfirmation(
                    name="Edited Existing Product",
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=9,
                    qu_factor_purchase_to_stock=4,
                ),
            )
        )
    )

    assert event["status"] == "applied"
    assert event["product_name"] == "Edited Existing Product"
    assert grocy.created == []
    assert grocy.updated[0][0] == 9
    assert grocy.updated[0][2].qu_id_stock == 7
    assert grocy.updated[0][2].qu_id_purchase == 9
    assert grocy.updated[0][2].qu_factor_purchase_to_stock == 4


def test_failed_known_product_operation_keeps_product_context(tmp_path) -> None:
    grocy = FakeGrocy(details(name="Diet Coca-Cola"), fail_apply=RuntimeError("Not enough stock"))
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    event = run(scanner.process(request()))

    assert event["status"] == "failed"
    assert event["product_id"] == 7
    assert event["product_name"] == "Diet Coca-Cola"
    assert event["stock_before"] == 2
    assert event["error"] == "Not enough stock"


def test_unknown_product_becomes_pending_with_lookup_suggestion(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Suggested Product",
        image_url="https://example.test/image.jpg",
        source="test",
        confidence=0.7,
    )
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=True, result=result)),
    )

    event = run(scanner.process(request()))

    assert event["status"] == "pending"
    assert event["product_name"] == "Suggested Product"
    assert event["lookup_payload"]["result"]["source"] == "test"


def test_device_scan_auto_creates_and_applies_complete_trusted_lookup_result(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))

    event = run(scanner.process(request()))

    assert event["status"] == "applied"
    assert event["product_name"] == "Trusted Product"
    assert len(grocy.created) == 1
    assert len(grocy.operations) == 1


def test_device_scan_trusts_agent_result_when_barcode_verified(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Verified Agent Product",
        image_url="https://example.test/image.jpg",
        source="agent_search",
        confidence=0.62,
        raw_payload={"barcode_verified": True},
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))

    event = run(scanner.process(request()))

    assert event["status"] == "applied"
    assert event["product_name"] == "Verified Agent Product"
    assert len(grocy.created) == 1
    assert len(grocy.operations) == 1


def test_refresh_uses_existing_grocy_product_after_lookup_was_already_created(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Trusted Product",
        image_url="https://example.test/image.jpg",
        source="open_food_facts",
        confidence=0.95,
    )
    grocy = FakeGrocy()
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=True, result=result)))
    pending = scanner.store.create(request())[0]
    scanner.store.update(pending["event_id"], status="pending", product_name="Trusted Product")
    grocy.product = details(22, "Trusted Product", 4)

    event = run(scanner.refresh(pending["event_id"]))

    assert event["status"] == "applied"
    assert event["product_name"] == "Trusted Product"
    assert len(grocy.created) == 0
    assert len(grocy.operations) == 1


def test_unknown_product_researching_status_is_preserved(tmp_path) -> None:
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False, research_status="queued")),
    )

    event = run(scanner.process(request()))

    assert event["status"] == "researching"


def test_confirm_creates_grocy_product_then_applies_original_operation(tmp_path) -> None:
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
    )
    run(scanner.process(request()))

    event = run(
        scanner.confirm(
            "event-1",
            PendingProductConfirmation(
                name="Confirmed Product",
                location_id=2,
                qu_id_stock=2,
                qu_id_purchase=2,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    assert event["status"] == "applied"
    assert event["product_name"] == "Confirmed Product"
    assert len(scanner.grocy.created) == 1
    assert len(scanner.grocy.operations) == 1


def test_confirm_exports_user_confirmed_product_to_catalog(tmp_path) -> None:
    catalog = FakeCommunityCatalog()
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
        community_catalog=catalog,
    )
    run(scanner.process(request()))

    run(
        scanner.confirm(
            "event-1",
            PendingProductConfirmation(
                name="Confirmed Product",
                brand="Confirmed Brand",
                quantity="500 mL",
                catalog_contribution=True,
                location_id=2,
                qu_id_stock=2,
                qu_id_purchase=2,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    assert len(catalog.exported) == 1
    barcode, product, result_source = catalog.exported[0]
    assert barcode == "123456"
    assert product.name == "Confirmed Product"
    assert product.brand == "Confirmed Brand"
    assert product.quantity == "500 mL"
    assert result_source is None


def test_confirm_exports_ai_search_result_to_catalog_with_source(tmp_path) -> None:
    catalog = FakeCommunityCatalog()
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(
            LookupResponse(
                barcode="123456",
                found=True,
                result=LookupResult(
                    barcode="123456",
                    name="Suggested Product",
                    source="llm_fallback",
                    confidence=0.8,
                ),
            )
        ),
        community_catalog=catalog,
    )
    run(scanner.process(request()))

    run(
        scanner.confirm(
            "event-1",
            PendingProductConfirmation(
                name="Confirmed Product",
                brand="Confirmed Brand",
                quantity="500 mL",
                catalog_contribution=False,
                location_id=2,
                qu_id_stock=2,
                qu_id_purchase=2,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    assert len(catalog.exported) == 1
    barcode, product, result_source = catalog.exported[0]
    assert barcode == "123456"
    assert product.name == "Confirmed Product"
    assert result_source == "llm_fallback"


def test_dashboard_confirm_exports_ai_search_result_to_catalog_with_source(tmp_path) -> None:
    catalog = FakeCommunityCatalog()
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
        community_catalog=catalog,
    )

    event = run(
        scanner.confirm_dashboard_scan(
            DashboardScanConfirmation(
                event_id="dashboard-lookup",
                device_id="dashboard-manual",
                barcode="123456",
                mode="add",
                quantity=1,
                product=PendingProductConfirmation(
                    name="Lookup Product",
                    brand="Lookup Brand",
                    quantity="12 oz",
                    lookup_source="web_search",
                    catalog_contribution=False,
                    location_id=4,
                    qu_id_stock=7,
                    qu_id_purchase=7,
                    qu_factor_purchase_to_stock=1,
                ),
            )
        )
    )

    assert event["status"] == "applied"
    assert len(catalog.exported) == 1
    barcode, product, result_source = catalog.exported[0]
    assert barcode == "123456"
    assert product.name == "Lookup Product"
    assert result_source == "web_search"


def test_confirm_still_applies_scan_when_catalog_export_fails(tmp_path) -> None:
    scanner = service(
        tmp_path,
        FakeGrocy(),
        FakeLookup(LookupResponse(barcode="123456", found=False)),
        community_catalog=FakeCommunityCatalog(error=RuntimeError("git failed")),
    )
    run(scanner.process(request()))

    event = run(
        scanner.confirm(
            "event-1",
            PendingProductConfirmation(
                name="Confirmed Product",
                location_id=2,
                qu_id_stock=2,
                qu_id_purchase=2,
                qu_factor_purchase_to_stock=1,
            ),
        )
    )

    assert event["status"] == "applied"
    assert event["product_name"] == "Confirmed Product"


def test_product_edit_history_store_records_before_after_snapshot(tmp_path) -> None:
    store = ProductEditHistoryStore(str(tmp_path / "history.sqlite3"))

    history_entry = store.create(
        product_id=7,
        barcode="123456",
        source="dashboard",
        changed_fields=["name"],
        before={"name": "Known Product"},
        after={"name": "Corrected Product"},
    )

    assert isinstance(history_entry, ProductEditHistoryEntry)
    stored = store.get(history_entry.id)
    assert isinstance(stored, ProductEditHistoryEntry)
    assert stored.product_id == 7
    assert stored.barcode == "123456"
    assert stored.changed_fields == ["name"]
    assert stored.before == {"name": "Known Product"}
    assert stored.after == {"name": "Corrected Product"}
    assert stored.created_at.endswith("Z")
    assert "T" in stored.created_at

    listing = store.list(limit=10, offset=0, sort="created_at", order="desc", query="")
    assert listing.total == 1
    assert listing.items[0].id == history_entry.id
    assert listing.sort == "created_at"
    assert listing.order == "desc"


def test_product_edit_history_store_filters_rows_by_server_side_query(tmp_path) -> None:
    store = ProductEditHistoryStore(str(tmp_path / "history.sqlite3"))
    store.create(
        product_id=7,
        barcode="123456",
        source="dashboard",
        changed_fields=["name", "brand"],
        before={"name": "Known Product", "brand": "Old"},
        after={"name": "Corrected Product", "brand": "New"},
    )
    store.create(
        product_id=8,
        barcode="999999",
        source="dashboard",
        changed_fields=["name"],
        before={"name": "Milk"},
        after={"name": "Whole Milk"},
    )

    result = store.list(limit=25, offset=0, sort="created_at", order="desc", query="123456")

    assert result.total == 1
    assert [item.barcode for item in result.items] == ["123456"]
    assert result.query == "123456"


def test_product_edit_history_store_returns_detail_with_field_diffs(tmp_path) -> None:
    store = ProductEditHistoryStore(str(tmp_path / "history.sqlite3"))
    entry = store.create(
        product_id=7,
        barcode="123456",
        source="dashboard",
        changed_fields=["name", "brand"],
        before={"name": "Known Product", "brand": "Old"},
        after={"name": "Corrected Product", "brand": "New"},
    )

    detail = store.detail(entry.id)

    assert isinstance(detail, ProductEditHistoryDetailResponse)
    assert detail.entry.id == entry.id
    assert detail.diffs[0] == ProductEditHistoryDiffField(
        field="name",
        before="Known Product",
        after="Corrected Product",
    )


def test_product_edit_history_store_groups_barcode_summary_rows(tmp_path) -> None:
    store = ProductEditHistoryStore(str(tmp_path / "history.sqlite3"))
    store.create(
        product_id=7,
        barcode="123456",
        source="dashboard",
        changed_fields=["name"],
        before={"name": "Known Product"},
        after={"name": "Corrected Product"},
    )
    store.create(
        product_id=7,
        barcode="123456",
        source="dashboard",
        changed_fields=["brand"],
        before={"brand": "Old"},
        after={"brand": "New"},
    )

    result = store.barcode_summary(limit=25, offset=0, sort="edit_count", order="desc", query="")

    assert isinstance(result, ProductEditHistoryBarcodeListResponse)
    assert result.total == 1
    assert result.items[0].barcode == "123456"
    assert result.items[0].product_name == "Corrected Product"
    assert result.items[0].edit_count == 2


def test_backfill_product_snapshot_updates_applied_events_by_product_id_and_barcode(tmp_path) -> None:
    store = ScanEventStore(str(tmp_path / "events.sqlite3"))

    store.create(
        ScanEventRequest(
            event_id="applied-by-product-id",
            device_id="kitchen-pi",
            barcode="111111",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    store.update(
        "applied-by-product-id",
        status="applied",
        product_id=7,
        product_name="Old Name",
        image_url="https://old.example/1.jpg",
        stock_before=2,
        stock_after=3,
        error="keep me",
    )

    store.create(
        ScanEventRequest(
            event_id="applied-by-barcode",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    store.update(
        "applied-by-barcode",
        status="applied",
        product_id=99,
        product_name="Old Name",
        image_url="https://old.example/2.jpg",
        stock_before=4,
        stock_after=5,
    )

    store.create(
        ScanEventRequest(
            event_id="applied-barcode-fallback",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    store.update(
        "applied-barcode-fallback",
        status="applied",
        product_name="Old Name",
        image_url="https://old.example/4.jpg",
        stock_before=8,
        stock_after=9,
    )

    store.create(
        ScanEventRequest(
            event_id="pending-match",
            device_id="kitchen-pi",
            barcode="123456",
            mode="add",
            quantity=1,
            location_id=2,
        )
    )
    store.update(
        "pending-match",
        status="pending",
        product_id=7,
        product_name="Old Name",
        image_url="https://old.example/3.jpg",
        stock_before=6,
        stock_after=7,
    )

    count = store.backfill_product_snapshot(
        product_id=7,
        barcode="123456",
        product_name="New Name",
        image_url="https://new.example/updated.jpg",
    )

    assert count == 2

    applied_by_product_id = store.get("applied-by-product-id")
    applied_by_barcode = store.get("applied-by-barcode")
    applied_barcode_fallback = store.get("applied-barcode-fallback")
    pending_match = store.get("pending-match")

    assert applied_by_product_id["status"] == "applied"
    assert applied_by_product_id["product_id"] == 7
    assert applied_by_product_id["barcode"] == "111111"
    assert applied_by_product_id["product_name"] == "New Name"
    assert applied_by_product_id["image_url"] == "https://new.example/updated.jpg"
    assert applied_by_product_id["stock_before"] == 2
    assert applied_by_product_id["stock_after"] == 3
    assert applied_by_product_id["error"] == "keep me"

    assert applied_by_barcode["status"] == "applied"
    assert applied_by_barcode["product_id"] == 99
    assert applied_by_barcode["barcode"] == "123456"
    assert applied_by_barcode["product_name"] == "Old Name"
    assert applied_by_barcode["image_url"] == "https://old.example/2.jpg"
    assert applied_by_barcode["stock_before"] == 4
    assert applied_by_barcode["stock_after"] == 5

    assert applied_barcode_fallback["status"] == "applied"
    assert applied_barcode_fallback["product_id"] is None
    assert applied_barcode_fallback["barcode"] == "123456"
    assert applied_barcode_fallback["product_name"] == "New Name"
    assert applied_barcode_fallback["image_url"] == "https://new.example/updated.jpg"
    assert applied_barcode_fallback["stock_before"] == 8
    assert applied_barcode_fallback["stock_after"] == 9

    assert pending_match["status"] == "pending"
    assert pending_match["product_id"] == 7
    assert pending_match["product_name"] == "Old Name"
    assert pending_match["image_url"] == "https://old.example/3.jpg"
