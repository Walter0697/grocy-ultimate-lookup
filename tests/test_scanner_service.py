import asyncio
from types import SimpleNamespace

from app.models import (
    DashboardScanConfirmation,
    DeviceScanRequest,
    LookupResponse,
    LookupResult,
    PendingProductConfirmation,
    ScanEventRequest,
)
from app.auto_created_store import AutoCreatedProductStore
from app.local_store import LocalProductStore
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


class FakeGrocy:
    def __init__(self, product=None, fail_apply: Exception | None = None) -> None:
        self.product = product
        self.fail_apply = fail_apply
        self.operations = []
        self.created = []
        self.updated = []

    async def find_product_by_barcode(self, barcode: str):
        return self.product

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


def test_dashboard_products_marks_auto_created_products_as_editable(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))
    scanner.auto_created_store.upsert(product_id=7, barcode="123456", source="open_food_facts")

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


def test_dashboard_products_marks_unowned_products_as_not_editable(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    products = run(scanner.products())

    assert products == [
        {
            "product_id": 7,
            "name": "Known Product",
            "image_url": None,
            "stock_amount": 2,
            "editable": False,
        }
    ]


def test_dashboard_products_defaults_to_not_editable_when_ownership_read_fails(tmp_path, caplog) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))
    scanner.auto_created_store = ReadFailingAutoCreatedStore()

    with caplog.at_level("WARNING"):
        products = run(scanner.products())

    assert products == [
        {
            "product_id": 7,
            "name": "Known Product",
            "image_url": None,
            "stock_amount": 2,
            "editable": False,
        }
    ]
    assert "Auto-created product ownership read failed for 7: ownership store read failed" in caplog.text


def test_dashboard_products_raises_for_malformed_product_id(tmp_path) -> None:
    grocy = FakeGrocy({"product": {"id": "broken", "name": "Known Product"}, "stock_amount": 2})
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    try:
        run(scanner.products())
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "invalid literal" in str(exc)


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
