import json
import logging
from uuid import uuid4

from app.app_settings import AppSettingsStore
from app.auto_created_store import AutoCreatedProductStore
from app.community_catalog import AI_SEARCH_SOURCES, RuntimeCommunityCatalogExporter
from app.config import settings
from app.grocy import GrocyClient
from app.local_store import LocalProductStore
from app.models import (
    DashboardProductEditResult,
    DashboardProductEditProductSummary,
    ConfirmedProductRequest,
    DashboardProductUpdate,
    DashboardScanConfirmation,
    DeviceScanRequest,
    PendingProductConfirmation,
    ScanEventRequest,
)
from app.orchestrator import LookupOrchestrator
from app.product_edit_history import ProductEditHistoryStore
from app.scan_events import ScanEventStore

logger = logging.getLogger(__name__)


class ScannerService:
    def __init__(
        self,
        store: ScanEventStore | None = None,
        grocy: GrocyClient | None = None,
        lookup: LookupOrchestrator | None = None,
        settings_store: AppSettingsStore | None = None,
        local_store: LocalProductStore | None = None,
        auto_created_store: AutoCreatedProductStore | None = None,
        history_store: ProductEditHistoryStore | None = None,
        community_catalog=None,
    ) -> None:
        self.settings_store = settings_store or AppSettingsStore(settings.app_settings_path)
        self.store = store or ScanEventStore(settings.scan_events_path)
        self.grocy = grocy or GrocyClient()
        self.lookup = lookup or LookupOrchestrator()
        self.local_store = local_store or LocalProductStore(settings.local_products_path)
        self.auto_created_store = auto_created_store or AutoCreatedProductStore(settings.auto_created_products_path)
        history_path = self.store.path.parent / "product-edit-history.sqlite3"
        self.history_store = history_store or ProductEditHistoryStore(str(history_path))
        self.community_catalog = community_catalog or RuntimeCommunityCatalogExporter(
            self.settings_store
        )

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
            qu_id_stock=int(units[0]["id"]),
            qu_id_purchase=int(units[0]["id"]),
            qu_factor_purchase_to_stock=1,
        )
        created = await self.grocy.create_product(barcode, product)
        product_id = int(created["product"]["id"])
        try:
            self.auto_created_store.upsert(
                product_id=product_id,
                barcode=barcode,
                source=result.source,
            )
        except Exception as exc:
            logger.warning("Auto-created product ownership write failed for %s: %s", barcode, exc)
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
        barcode_verified = bool((result.raw_payload or {}).get("barcode_verified")) if result else False
        trusted_confidence = result.confidence >= settings.auto_create_min_confidence if result else False
        trusted_agent = result.source == "agent_search" and barcode_verified if result else False
        return bool(
            response.found
            and result
            and result.name.strip()
            and result.image_url
            and (trusted_confidence or trusted_agent)
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
        existing = await self._confirm_product(
            event["barcode"],
            product,
            result_source=self._event_lookup_source(event),
        )
        return await self._apply(self._request_from_event(event), existing)

    async def confirm_dashboard_scan(self, confirmation: DashboardScanConfirmation) -> dict:
        request = ScanEventRequest(
            event_id=confirmation.event_id,
            device_id=confirmation.device_id,
            barcode=confirmation.barcode,
            mode=confirmation.mode,
            quantity=confirmation.quantity,
            location_id=confirmation.location_id,
        )
        event, created = self.store.create(request)
        if not created:
            return event
        try:
            product = await self._confirm_product(
                confirmation.barcode,
                confirmation.product,
                result_source=confirmation.product.lookup_source,
            )
            return await self._apply(request, product)
        except Exception as exc:
            return self.store.update(
                request.event_id,
                status="failed",
                product_name=confirmation.product.name,
                error=str(exc),
            )

    async def _confirm_product(
        self,
        barcode: str,
        product: PendingProductConfirmation,
        *,
        result_source: str | None = None,
    ) -> dict:
        existing = await self.grocy.find_product_by_barcode(barcode)
        if existing is None:
            existing = await self.grocy.create_product(barcode, product)
        else:
            existing = await self.grocy.update_product(int(existing["product"]["id"]), barcode, product)
        self.local_store.upsert(
            barcode,
            ConfirmedProductRequest(
                name=product.name,
                brand=product.brand,
                quantity=product.quantity,
                image_url=product.image_url,
                notes="Confirmed from external scanner dashboard",
            ),
        )
        if product.catalog_contribution or result_source in AI_SEARCH_SOURCES:
            catalog_product = ConfirmedProductRequest(
                name=product.name,
                brand=product.brand,
                quantity=product.quantity,
                image_url=product.image_url,
                notes=product.description,
            )
            try:
                result = self.community_catalog.export_confirmed_product(
                    barcode,
                    catalog_product,
                    result_source=result_source,
                )
                for warning in result.warnings:
                    logger.warning("Community catalog export warning for %s: %s", barcode, warning)
            except Exception as exc:
                logger.warning("Community catalog export failed for %s: %s", barcode, exc)
        return existing

    async def products(self) -> list[dict]:
        products = await self.grocy.dashboard_products()
        for product in products:
            product["editable"] = True
        return products

    async def options(self) -> dict:
        return {
            "locations": await self.grocy.get_objects("locations"),
            "quantity_units": await self.grocy.get_objects("quantity_units"),
        }

    async def update_dashboard_product(self, product_id: int, update: DashboardProductUpdate) -> dict:
        barcode, existing = await self._load_dashboard_product(product_id)

        before_snapshot = self._dashboard_product_snapshot(existing)
        original_source = self._original_product_source(product_id, before_snapshot)
        update_payload = update.model_dump()
        export_image_url = update_payload.get("image_url")
        if before_snapshot.get("image_url") and str(update.image_url or "") == str(before_snapshot["image_url"]):
            update_payload["image_url"] = None
            export_image_url = None
        updated = await self.grocy.update_product(
            product_id,
            barcode,
            PendingProductConfirmation(**update_payload),
        )
        return self._finalize_dashboard_product_update(
            product_id=product_id,
            barcode=barcode,
            before_snapshot=before_snapshot,
            updated=updated,
            source="dashboard",
            original_source=original_source,
            export_image_url=str(export_image_url) if export_image_url else None,
        )

    async def request_image_review(self, product_id: int) -> dict:
        existing_review = self.store.get_open_review(product_id=product_id, review_kind="image_update")
        if existing_review is not None:
            return existing_review

        barcode, product = await self._load_dashboard_product(product_id)
        card = self.grocy.product_card(product)
        snapshot = self._dashboard_product_snapshot(product)
        return self.store.create_review_event(
            event_id=f"review-image-{uuid4().hex}",
            device_id="dashboard-review",
            barcode=barcode,
            location_id=snapshot.get("location_id"),
            product_id=product_id,
            product_name=card.get("name"),
            image_url=card.get("image_url"),
            review_kind="image_update",
            lookup_payload={
                "review_only": True,
                "review_kind": "image_update",
                "product": snapshot,
            },
        )

    def request_catalog_image_review(
        self,
        *,
        barcode: str,
        product_name: str,
        variant_id: str,
        location_id: int | None = None,
    ) -> dict:
        existing_review = self.store.get_open_review_by_barcode(
            barcode=barcode,
            review_kind="catalog_image",
        )
        if existing_review is not None:
            return existing_review

        return self.store.create_review_event(
            event_id=f"review-catalog-image-{uuid4().hex}",
            device_id="items-page",
            barcode=barcode,
            location_id=location_id,
            product_id=None,
            product_name=product_name,
            image_url=None,
            review_kind="catalog_image",
            lookup_payload={
                "review_only": True,
                "review_kind": "catalog_image",
                "variant_id": variant_id,
            },
        )

    async def attach_image_to_event(self, event_id: str, image_url: str) -> dict:
        event = self._required(event_id)
        if event.get("review_kind") == "catalog_image":
            payload = event.get("lookup_payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            completed = self.store.update(
                event_id,
                status="dismissed",
                image_url=image_url,
                lookup_payload={
                    **payload,
                    "catalog_image_ready": True,
                    "review_kind": "catalog_image",
                },
                error=None,
            )
            completed["review_dismissed"] = True
            return completed

        updated_event = self.store.update(event_id, image_url=image_url)
        product_id = updated_event.get("product_id")
        if product_id is None:
            return updated_event

        barcode, existing = await self._load_dashboard_product(int(product_id), barcode=updated_event.get("barcode"))
        before_snapshot = self._dashboard_product_snapshot(existing)
        original_source = self._original_product_source(int(product_id), before_snapshot)
        update_payload = PendingProductConfirmation(
            name=before_snapshot.get("name") or updated_event.get("product_name") or "Unnamed product",
            description=before_snapshot.get("description"),
            brand=before_snapshot.get("brand"),
            quantity=before_snapshot.get("quantity"),
            image_url=image_url,
            location_id=int(before_snapshot.get("location_id") or updated_event.get("location_id") or 1),
            qu_id_stock=int(before_snapshot.get("qu_id_stock") or 1),
            qu_id_purchase=int(before_snapshot.get("qu_id_purchase") or 1),
            qu_factor_purchase_to_stock=float(before_snapshot.get("qu_factor_purchase_to_stock") or 1),
        )
        updated = await self.grocy.update_product(int(product_id), barcode, update_payload)
        result = self._finalize_dashboard_product_update(
            product_id=int(product_id),
            barcode=barcode,
            before_snapshot=before_snapshot,
            updated=updated,
            source="telegram_review_upload",
            related_event_id=event_id,
            original_source=original_source,
            export_image_url=image_url,
        )
        completed_event = self.store.update(
            event_id,
            status="applied",
            product_name=result["product"]["name"],
            image_url=result["product"].get("image_url"),
            error=None,
        )
        self.store.delete(event_id)
        completed_event["status"] = "dismissed"
        completed_event["review_dismissed"] = True
        return completed_event

    async def _load_dashboard_product(self, product_id: int, *, barcode: str | None = None) -> tuple[str, dict]:
        record = self.auto_created_store.get_by_product_id(product_id)
        resolved_barcode = barcode or (record["barcode"] if record is not None else await self.grocy.get_product_barcode(product_id))
        if resolved_barcode is None:
            raise KeyError(product_id)

        existing = await self.grocy.find_product_by_barcode(resolved_barcode)
        if existing is None or int(existing["product"]["id"]) != product_id:
            raise KeyError(product_id)
        return resolved_barcode, existing

    def _finalize_dashboard_product_update(
        self,
        *,
        product_id: int,
        barcode: str,
        before_snapshot: dict,
        updated: dict,
        source: str,
        related_event_id: str | None = None,
        original_source: str | None = None,
        export_image_url: str | None = None,
    ) -> dict:
        after_snapshot = self._dashboard_product_snapshot(updated)
        product = self._dashboard_product_summary(updated)
        changed_fields = sorted(
            field for field in before_snapshot.keys() | after_snapshot.keys() if before_snapshot.get(field) != after_snapshot.get(field)
        )
        history_entry = None
        if changed_fields:
            try:
                history_entry = self.history_store.create(
                    product_id=product_id,
                    barcode=barcode,
                    source=source,
                    changed_fields=changed_fields,
                    before={field: before_snapshot.get(field) for field in changed_fields},
                    after={field: after_snapshot.get(field) for field in changed_fields},
                    related_event_id=related_event_id,
                )
            except Exception as exc:
                logger.warning("Product edit history write failed for %s: %s", barcode, exc)

        updated_event_count = 0
        try:
            updated_event_count = self.store.backfill_product_snapshot(
                product_id=product_id,
                barcode=barcode,
                product_name=product["name"],
                image_url=product["image_url"],
            )
        except Exception as exc:
            logger.warning("Applied scan event backfill failed for %s: %s", barcode, exc)

        if changed_fields:
            self._export_modified_product(
                barcode=barcode,
                snapshot=after_snapshot,
                original_source=original_source,
                export_image_url=export_image_url,
            )

        return DashboardProductEditResult(
            product=DashboardProductEditProductSummary.model_validate(product),
            updated_event_count=updated_event_count,
            history_entry=history_entry,
        ).model_dump(mode="json")

    async def _lookup_pending(self, request: ScanEventRequest) -> dict:
        response = await self.lookup.lookup(request.barcode, use_cache=False)
        result = response.result
        if self._can_auto_create(response):
            product = await self.grocy.find_product_by_barcode(request.barcode)
            if product is None:
                product = await self._create_from_lookup(request.barcode, result)
            self.store.update(
                request.event_id,
                product_name=result.name,
                image_url=str(result.image_url) if result.image_url else None,
                lookup_payload=response.model_dump(mode="json"),
                error=None,
            )
            return await self._apply(request, product)
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
        initial_card = self.grocy.product_card(grocy_product)
        try:
            updated = await self.grocy.apply_stock_operation(int(grocy_product["product"]["id"]), request)
        except Exception as exc:
            return self.store.update(
                request.event_id,
                status="failed",
                product_id=initial_card["product_id"],
                product_name=initial_card["name"],
                image_url=initial_card["image_url"],
                stock_before=before,
                error=str(exc),
            )
        card = self.grocy.product_card(updated)
        event = self.store.update(
            request.event_id,
            status="applied",
            product_id=card["product_id"],
            product_name=card["name"],
            image_url=card["image_url"],
            stock_before=before,
            stock_after=float(card["stock_amount"] or 0),
            error=None,
        )
        await self._ensure_missing_image_review(
            product_id=int(card["product_id"]),
            barcode=request.barcode,
            grocy_product=updated,
        )
        return event

    def _required(self, event_id: str) -> dict:
        event = self.store.get(event_id)
        if event is None:
            raise KeyError(event_id)
        return event

    @staticmethod
    def _event_lookup_source(event: dict) -> str | None:
        payload = event.get("lookup_payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        source = result.get("source")
        return source if isinstance(source, str) else None

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

    def _dashboard_product_summary(self, product: dict) -> dict:
        card = self.grocy.product_card(product)
        return {
            "product_id": card["product_id"],
            "name": card["name"],
            "image_url": card.get("image_url"),
            "stock_amount": card.get("stock_amount"),
            "editable": True,
        }

    def _dashboard_product_snapshot(self, product: dict) -> dict:
        product_data = product.get("product") or {}
        card = self.grocy.product_card(product)
        return {
            "name": product_data.get("name"),
            "description": product_data.get("description"),
            "brand": product_data.get("brand"),
            "quantity": product_data.get("quantity"),
            "image_url": card.get("image_url"),
            "location_id": product_data.get("location_id"),
            "qu_id_stock": product_data.get("qu_id_stock"),
            "qu_id_purchase": product_data.get("qu_id_purchase"),
            "qu_factor_purchase_to_stock": product_data.get("qu_factor_purchase_to_stock"),
        }

    def _export_modified_product(
        self,
        *,
        barcode: str,
        snapshot: dict,
        original_source: str | None,
        export_image_url: str | None = None,
    ) -> None:
        export_product = ConfirmedProductRequest(
            name=snapshot.get("name") or "Unnamed product",
            brand=snapshot.get("brand"),
            quantity=snapshot.get("quantity"),
            image_url=export_image_url or snapshot.get("image_url"),
            notes=snapshot.get("description"),
        )
        try:
            result = self.community_catalog.export_confirmed_product(
                barcode,
                export_product,
                export_reason="modified",
                original_source=original_source,
            )
            for warning in result.warnings:
                logger.warning("Community catalog export warning for modified %s: %s", barcode, warning)
        except Exception as exc:
            logger.warning("Community catalog export failed for modified %s: %s", barcode, exc)

    def _original_product_source(self, product_id: int, snapshot: dict) -> str | None:
        try:
            record = self.auto_created_store.get_by_product_id(product_id)
        except Exception as exc:
            logger.warning("Auto-created product ownership read failed for %s: %s", product_id, exc)
            record = None
        if record is not None:
            source = record.get("source")
            if isinstance(source, str) and source.strip():
                return source.strip()
        description = snapshot.get("description")
        if not isinstance(description, str):
            return None
        for line in description.splitlines():
            if not line.startswith("Lookup source:"):
                continue
            source = line.split(":", 1)[1].strip()
            return source or None
        return None

    async def _ensure_missing_image_review(
        self,
        *,
        product_id: int,
        barcode: str,
        grocy_product: dict,
    ) -> None:
        if not self.settings_store.get_lookup().auto_request_missing_images:
            return
        card = self.grocy.product_card(grocy_product)
        if card.get("image_url"):
            return
        if self.store.get_open_review(product_id=product_id, review_kind="image_update") is not None:
            return
        snapshot = self._dashboard_product_snapshot(grocy_product)
        self.store.create_review_event(
            event_id=f"review-image-{uuid4().hex}",
            device_id="auto-image-review",
            barcode=barcode,
            location_id=snapshot.get("location_id"),
            product_id=product_id,
            product_name=card.get("name"),
            image_url=None,
            review_kind="image_update",
            lookup_payload={
                "review_only": True,
                "review_kind": "image_update",
                "reason": "missing_product_image",
                "product": snapshot,
            },
        )
