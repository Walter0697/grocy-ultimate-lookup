import asyncio

from app.models import LookupResponse, LookupResult, PendingProductConfirmation, ScanEventRequest
from app.local_store import LocalProductStore
from app.scan_events import ScanEventStore
from app.scanner_service import ScannerService


class FakeLookup:
    def __init__(self, response: LookupResponse) -> None:
        self.response = response
        self.calls = []

    async def lookup(self, barcode: str, use_cache: bool = False) -> LookupResponse:
        self.calls.append((barcode, use_cache))
        return self.response


class FakeGrocy:
    def __init__(self, product=None) -> None:
        self.product = product
        self.operations = []
        self.created = []

    async def find_product_by_barcode(self, barcode: str):
        return self.product

    async def apply_stock_operation(self, product_id: int, event: ScanEventRequest):
        self.operations.append((product_id, event))
        name = self.product["product"]["name"]
        self.product = details(product_id, name, event.quantity if event.mode == "set" else 3)
        return self.product

    async def create_product(self, barcode: str, product: PendingProductConfirmation):
        self.created.append((barcode, product))
        self.product = details(22, product.name, 0)
        return self.product

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
    )


def service(tmp_path, grocy, lookup):
    scanner = ScannerService(
        store=ScanEventStore(str(tmp_path / "events.sqlite3")),
        grocy=grocy,
        lookup=lookup,
        local_store=LocalProductStore(str(tmp_path / "local.sqlite3")),
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


def test_duplicate_event_id_does_not_apply_stock_twice(tmp_path) -> None:
    grocy = FakeGrocy(details())
    scanner = service(tmp_path, grocy, FakeLookup(LookupResponse(barcode="123456", found=False)))

    first = run(scanner.process(request()))
    second = run(scanner.process(request()))

    assert first == second
    assert len(grocy.operations) == 1


def test_unknown_product_becomes_pending_with_lookup_suggestion(tmp_path) -> None:
    result = LookupResult(
        barcode="123456",
        name="Suggested Product",
        image_url="https://example.test/image.jpg",
        source="test",
        confidence=0.8,
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
                qu_id=2,
            ),
        )
    )

    assert event["status"] == "applied"
    assert event["product_name"] == "Confirmed Product"
    assert len(scanner.grocy.created) == 1
    assert len(scanner.grocy.operations) == 1
