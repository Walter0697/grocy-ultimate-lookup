from uuid import uuid4

from app.config import settings
from app.grocy import GrocyClient
from app.local_store import LocalProductStore
from app.models import ConfirmedProductRequest, DeviceScanRequest, PendingProductConfirmation, ScanEventRequest
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

    async def process_device_scan(self, request: DeviceScanRequest) -> dict:
        event = await self.process(
            ScanEventRequest(
                event_id=self._device_event_id(request.device_id),
                device_id=request.device_id,
                barcode=request.barcode,
                mode=request.mode,
                quantity=request.quantity,
                location_id=request.location_id,
            )
        )
        return self._device_response(event)

    async def preview(self, barcode: str) -> dict:
        grocy_product = await self.grocy.find_product_by_barcode(barcode)
        if grocy_product is not None:
            return self._preview_response(barcode, grocy_product, "grocy")
        response = await self.lookup.lookup(barcode, use_cache=False)
        if self._can_auto_create(response):
            product = await self._create_from_lookup(barcode, response.result)
            return self._preview_response(
                barcode,
                product,
                "grocy_auto_created",
                lookup=response.model_dump(mode="json"),
            )
        return {
            "barcode": barcode,
            "found": response.found,
            "resolution": "lookup" if response.found else "unknown",
            "product": response.result.model_dump(mode="json") if response.result else None,
            "lookup": response.model_dump(mode="json"),
        }

    async def _create_from_lookup(self, barcode: str, result) -> dict:
        locations = await self.grocy.get_objects("locations")
        units = await self.grocy.get_objects("quantity_units")
        if not locations or not units:
            raise RuntimeError("Grocy needs at least one location and quantity unit before products can be created")
        description_parts = [
            f"Lookup source: {result.source}",
            f"Lookup confidence: {result.confidence}",
        ]
        if result.raw_url:
            description_parts.append(f"Source URL: {result.raw_url}")
        product = PendingProductConfirmation(
            name=result.name,
            description="\n".join(description_parts),
            brand=result.brand,
            quantity=result.quantity or result.size,
            image_url=result.image_url,
            location_id=int(locations[0]["id"]),
            qu_id=int(units[0]["id"]),
        )
        created = await self.grocy.create_product(barcode, product)
        self.local_store.upsert(
            barcode,
            ConfirmedProductRequest(
                name=result.name,
                brand=result.brand,
                quantity=result.quantity or result.size,
                image_url=result.image_url,
                notes="Automatically created from a trusted lookup result",
            ),
        )
        return created

    def _preview_response(self, barcode: str, product: dict, resolution: str, lookup: dict | None = None) -> dict:
        return {
            "barcode": barcode,
            "found": True,
            "resolution": resolution,
            "product": self.grocy.product_card(product),
            "lookup": lookup,
        }

    @staticmethod
    def _can_auto_create(response) -> bool:
        result = response.result
        return bool(
            response.found
            and result
            and result.name.strip()
            and result.image_url
            and result.confidence >= settings.auto_create_min_confidence
            and not result.match_warnings
            and response.research_status not in {"queued", "running"}
        )

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

    @staticmethod
    def _device_event_id(device_id: str) -> str:
        safe_device = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in device_id).strip("-")
        return f"{safe_device or 'device'}-{uuid4().hex}"

    @staticmethod
    def _device_response(event: dict) -> dict:
        needs_review = event["status"] in {"pending", "researching", "failed"}
        if event["status"] == "applied":
            message = f"{event['product_name'] or event['barcode']}: stock is now {event['stock_after']}"
        elif event["status"] == "pending":
            message = "Product needs dashboard review before stock can be changed"
        elif event["status"] == "researching":
            message = "Product lookup is still researching; check the dashboard"
        else:
            message = event.get("error") or "Scan failed; check the dashboard"
        return {
            "event_id": event["event_id"],
            "status": event["status"],
            "barcode": event["barcode"],
            "mode": event["mode"],
            "quantity": event["quantity"],
            "product_name": event["product_name"],
            "stock_before": event["stock_before"],
            "stock_after": event["stock_after"],
            "needs_review": needs_review,
            "message": message,
        }
