from app.config import settings
from app.grocy import GrocyClient
from app.local_store import LocalProductStore
from app.models import ConfirmedProductRequest, PendingProductConfirmation, ScanEventRequest
from app.orchestrator import LookupOrchestrator
from app.scan_events import ScanEventStore


class ScannerService:
    def __init__(
        self,
        store: ScanEventStore | None = None,
        grocy: GrocyClient | None = None,
        lookup: LookupOrchestrator | None = None,
        local_store: LocalProductStore | None = None,
    ) -> None:
        self.store = store or ScanEventStore(settings.scan_events_path)
        self.grocy = grocy or GrocyClient()
        self.lookup = lookup or LookupOrchestrator()
        self.local_store = local_store or LocalProductStore(settings.local_products_path)

    async def process(self, request: ScanEventRequest) -> dict:
        event, created = self.store.create(request)
        if not created:
            return event
        try:
            grocy_product = await self.grocy.find_product_by_barcode(request.barcode)
            if grocy_product is not None:
                return await self._apply(request, grocy_product)
            return await self._lookup_pending(request)
        except Exception as exc:
            return self.store.update(request.event_id, status="failed", error=str(exc))

    async def refresh(self, event_id: str) -> dict:
        event = self._required(event_id)
        if event["status"] not in {"pending", "researching"}:
            return event
        request = self._request_from_event(event)
        return await self._lookup_pending(request)

    async def confirm(self, event_id: str, product: PendingProductConfirmation) -> dict:
        event = self._required(event_id)
        if event["status"] not in {"pending", "researching", "failed"}:
            return event
        existing = await self.grocy.find_product_by_barcode(event["barcode"])
        if existing is None:
            existing = await self.grocy.create_product(event["barcode"], product)
        self.local_store.upsert(
            event["barcode"],
            ConfirmedProductRequest(
                name=product.name,
                brand=product.brand,
                quantity=product.quantity,
                image_url=product.image_url,
                notes="Confirmed from external scanner dashboard",
            ),
        )
        return await self._apply(self._request_from_event(event), existing)

    async def products(self) -> list[dict]:
        return await self.grocy.dashboard_products()

    async def options(self) -> dict:
        return {
            "locations": await self.grocy.get_objects("locations"),
            "quantity_units": await self.grocy.get_objects("quantity_units"),
        }

    async def _lookup_pending(self, request: ScanEventRequest) -> dict:
        response = await self.lookup.lookup(request.barcode, use_cache=False)
        result = response.result
        return self.store.update(
            request.event_id,
            status="researching" if response.research_status in {"queued", "running"} else "pending",
            product_name=result.name if result else None,
            image_url=str(result.image_url) if result and result.image_url else None,
            lookup_payload=response.model_dump(mode="json"),
            error=None,
        )

    async def _apply(self, request: ScanEventRequest, grocy_product: dict) -> dict:
        before = float(grocy_product.get("stock_amount") or 0)
        updated = await self.grocy.apply_stock_operation(int(grocy_product["product"]["id"]), request)
        card = self.grocy.product_card(updated)
        return self.store.update(
            request.event_id,
            status="applied",
            product_id=card["product_id"],
            product_name=card["name"],
            image_url=card["image_url"],
            stock_before=before,
            stock_after=float(card["stock_amount"] or 0),
            error=None,
        )

    def _required(self, event_id: str) -> dict:
        event = self.store.get(event_id)
        if event is None:
            raise KeyError(event_id)
        return event

    @staticmethod
    def _request_from_event(event: dict) -> ScanEventRequest:
        return ScanEventRequest(
            event_id=event["event_id"],
            device_id=event["device_id"],
            barcode=event["barcode"],
            mode=event["mode"],
            quantity=event["quantity"],
            location_id=event["location_id"],
        )
