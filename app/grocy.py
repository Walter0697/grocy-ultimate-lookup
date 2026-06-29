import base64
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from pydantic import HttpUrl

from app.config import settings
from app.models import PendingProductConfirmation, ScanEventRequest


class GrocyError(RuntimeError):
    pass


class GrocyClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.grocy_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.grocy_api_key

    def headers(self) -> dict[str, str]:
        return {"GROCY-API-KEY": self.api_key} if self.api_key else {}

    async def find_product_by_barcode(self, barcode: str) -> dict | None:
        barcodes = await self.get_objects("product_barcodes")
        barcode_row = next((item for item in barcodes if str(item.get("barcode")) == barcode), None)
        if barcode_row is None:
            return None
        return await self.product_details(int(barcode_row["product_id"]))

    async def product_details(self, product_id: int) -> dict:
        return await self._request("GET", f"/stock/products/{product_id}")

    async def get_product_object(self, product_id: int) -> dict:
        return await self._request("GET", f"/objects/products/{product_id}")

    async def get_objects(self, entity: str) -> list[dict]:
        return await self._request("GET", f"/objects/{entity}")

    async def create_quantity_unit(self, name: str) -> dict:
        return await self._request("POST", "/objects/quantity_units", json={"name": name})

    async def delete_product(self, product_id: int) -> None:
        await self._request("DELETE", f"/objects/products/{product_id}")

    async def get_product_barcode_row(self, product_id: int, barcode: str) -> dict | None:
        barcodes = await self.get_objects("product_barcodes")
        return next(
            (
                row
                for row in barcodes
                if int(row.get("product_id") or 0) == product_id and str(row.get("barcode")) == barcode
            ),
            None,
        )

    async def update_product_barcode(self, barcode_row_id: int, payload: dict) -> None:
        await self._request("PUT", f"/objects/product_barcodes/{barcode_row_id}", json=payload)

    async def create_product_barcode(self, payload: dict) -> dict:
        return await self._request("POST", "/objects/product_barcodes", json=payload)

    async def delete_product_barcode(self, barcode_row_id: int) -> None:
        await self._request("DELETE", f"/objects/product_barcodes/{barcode_row_id}")

    async def get_quantity_unit_conversions(self, product_id: int) -> list[dict]:
        return await self._request(
            "GET",
            "/objects/quantity_unit_conversions",
            params={"query[]": f"product_id={product_id}"},
        )

    async def create_quantity_unit_conversion(self, payload: dict) -> dict:
        return await self._request("POST", "/objects/quantity_unit_conversions", json=payload)

    async def update_quantity_unit_conversion(self, conversion_id: int, payload: dict) -> None:
        await self._request("PUT", f"/objects/quantity_unit_conversions/{conversion_id}", json=payload)

    async def delete_quantity_unit_conversion(self, conversion_id: int) -> None:
        await self._request("DELETE", f"/objects/quantity_unit_conversions/{conversion_id}")

    async def upsert_product_unit_conversions(
        self,
        product_id: int,
        purchase_qu_id: int,
        stock_qu_id: int,
        factor: float,
        previous_purchase_qu_id: int | None = None,
        previous_stock_qu_id: int | None = None,
    ) -> None:
        if purchase_qu_id == stock_qu_id:
            factor = 1
        existing = await self.get_quantity_unit_conversions(product_id)
        desired = [
            {
                "from_qu_id": purchase_qu_id,
                "to_qu_id": stock_qu_id,
                "factor": factor,
                "product_id": product_id,
            },
            {
                "from_qu_id": stock_qu_id,
                "to_qu_id": purchase_qu_id,
                "factor": 1 / factor,
                "product_id": product_id,
            },
        ]
        unique_desired = []
        seen_pairs = set()
        for payload in desired:
            pair = (payload["from_qu_id"], payload["to_qu_id"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            unique_desired.append(payload)
        desired_pairs = {(payload["from_qu_id"], payload["to_qu_id"]) for payload in unique_desired}
        reciprocal_pairs = {
            (int(row["from_qu_id"]), int(row["to_qu_id"]))
            for row in existing
            if int(row.get("product_id") or 0) == product_id
        }

        if purchase_qu_id != stock_qu_id:
            for row in existing:
                from_qu_id = int(row["from_qu_id"])
                to_qu_id = int(row["to_qu_id"])
                row_pair = (from_qu_id, to_qu_id)
                if row_pair in desired_pairs or int(row.get("product_id") or 0) != product_id:
                    continue
                if (
                    (to_qu_id == stock_qu_id and from_qu_id != purchase_qu_id)
                    or (from_qu_id == stock_qu_id and to_qu_id != purchase_qu_id)
                    or (from_qu_id == purchase_qu_id and to_qu_id != stock_qu_id)
                    or (to_qu_id == purchase_qu_id and from_qu_id != stock_qu_id)
                ):
                    await self.delete_quantity_unit_conversion(int(row["id"]))
        elif (
            previous_purchase_qu_id is not None
            and previous_stock_qu_id is not None
            and previous_purchase_qu_id != previous_stock_qu_id
        ):
            for row in existing:
                from_qu_id = int(row["from_qu_id"])
                to_qu_id = int(row["to_qu_id"])
                row_pair = (from_qu_id, to_qu_id)
                if row_pair in desired_pairs or int(row.get("product_id") or 0) != product_id:
                    continue
                if row_pair in {
                    (previous_purchase_qu_id, previous_stock_qu_id),
                    (previous_stock_qu_id, previous_purchase_qu_id),
                } and (to_qu_id, from_qu_id) in reciprocal_pairs:
                    await self.delete_quantity_unit_conversion(int(row["id"]))

        for payload in unique_desired:
            match = next(
                (
                    row
                    for row in existing
                    if int(row["from_qu_id"]) == payload["from_qu_id"]
                    and int(row["to_qu_id"]) == payload["to_qu_id"]
                    and int(row.get("product_id") or 0) == product_id
                ),
                None,
            )
            if match is None:
                await self.create_quantity_unit_conversion(payload)
            else:
                await self.update_quantity_unit_conversion(int(match["id"]), payload)

    async def get_purchase_to_stock_factor(self, product_id: int) -> float:
        product = await self.get_product_object(product_id)
        purchase_qu_id = int(product["qu_id_purchase"])
        stock_qu_id = int(product["qu_id_stock"])
        if purchase_qu_id == stock_qu_id:
            return 1.0

        conversions = await self.get_quantity_unit_conversions(product_id)
        match = next(
            (
                row
                for row in conversions
                if int(row.get("product_id") or 0) == product_id
                and int(row["from_qu_id"]) == purchase_qu_id
                and int(row["to_qu_id"]) == stock_qu_id
            ),
            None,
        )
        if match is None:
            raise GrocyError(
                f"Missing purchase-to-stock quantity unit conversion in Grocy for product {product_id}"
            )
        return float(match["factor"])

    async def apply_stock_operation(self, product_id: int, event: ScanEventRequest) -> dict:
        if event.mode == "add":
            factor = await self.get_purchase_to_stock_factor(product_id)
            payload = {
                "amount": event.quantity * factor,
                "transaction_type": "purchase",
                "note": event.event_id,
            }
            if event.location_id is not None:
                payload["location_id"] = event.location_id
            await self._request("POST", f"/stock/products/{product_id}/add", json=payload)
        elif event.mode == "remove":
            payload = {"amount": event.quantity, "transaction_type": "consume", "spoiled": False}
            if event.location_id is not None:
                payload["location_id"] = event.location_id
            await self._request("POST", f"/stock/products/{product_id}/consume", json=payload)
        else:
            payload = {"new_amount": event.quantity, "note": event.event_id}
            if event.location_id is not None:
                payload["location_id"] = event.location_id
            await self._request(
                "POST",
                f"/stock/products/{product_id}/inventory",
                json=payload,
            )
        return await self.product_details(product_id)

    async def create_product(
        self,
        barcode: str,
        product: PendingProductConfirmation,
    ) -> dict:
        picture_file_name = await self._upload_product_picture(barcode, product.image_url)
        payload = self.product_payload(product, picture_file_name=picture_file_name)
        payload.pop("qu_factor_purchase_to_stock", None)
        created = await self._request("POST", "/objects/products", json=payload)
        product_id = int(created["created_object_id"])
        try:
            await self._request(
                "POST",
                "/objects/product_barcodes",
                json={"product_id": product_id, "barcode": barcode, "qu_id": product.qu_id_purchase},
            )
            await self.upsert_product_unit_conversions(
                product_id,
                product.qu_id_purchase,
                product.qu_id_stock,
                product.qu_factor_purchase_to_stock,
            )
            return await self.product_details(product_id)
        except Exception:
            try:
                await self.delete_product(product_id)
            except Exception:
                pass
            raise

    async def update_product(
        self,
        product_id: int,
        barcode: str,
        product: PendingProductConfirmation,
    ) -> dict:
        picture_file_name = await self._upload_product_picture(barcode, product.image_url)
        payload = self.product_payload(product, picture_file_name=picture_file_name)
        payload.pop("qu_factor_purchase_to_stock", None)
        existing_product = await self.get_product_object(product_id)
        barcode_row = await self.get_product_barcode_row(product_id, barcode)
        existing_conversions = await self.get_quantity_unit_conversions(product_id)
        await self._request("PUT", f"/objects/products/{product_id}", json=payload)
        try:
            if barcode_row is not None:
                await self.update_product_barcode(
                    int(barcode_row["id"]),
                    {"product_id": product_id, "barcode": barcode, "qu_id": product.qu_id_purchase},
                )
            else:
                await self.create_product_barcode(
                    {"product_id": product_id, "barcode": barcode, "qu_id": product.qu_id_purchase}
                )
            await self.upsert_product_unit_conversions(
                product_id,
                product.qu_id_purchase,
                product.qu_id_stock,
                product.qu_factor_purchase_to_stock,
                previous_purchase_qu_id=int(existing_product["qu_id_purchase"]),
                previous_stock_qu_id=int(existing_product["qu_id_stock"]),
            )
            return await self.product_details(product_id)
        except Exception:
            try:
                await self.restore_product_update_state(
                    product_id,
                    barcode,
                    existing_product,
                    barcode_row,
                    existing_conversions,
                )
            except Exception:
                pass
            raise

    async def restore_product_update_state(
        self,
        product_id: int,
        barcode: str,
        product_snapshot: dict,
        barcode_row: dict | None,
        conversions: list[dict],
    ) -> None:
        await self._request("PUT", f"/objects/products/{product_id}", json=self.product_object_payload(product_snapshot))

        current_barcode_row = await self.get_product_barcode_row(product_id, barcode)
        if barcode_row is None:
            if current_barcode_row is not None:
                await self.delete_product_barcode(int(current_barcode_row["id"]))
        else:
            payload = {
                "product_id": product_id,
                "barcode": str(barcode_row["barcode"]),
                "qu_id": int(barcode_row["qu_id"]),
            }
            if current_barcode_row is None:
                await self.create_product_barcode(payload)
            else:
                await self.update_product_barcode(int(current_barcode_row["id"]), payload)

        current_conversions = await self.get_quantity_unit_conversions(product_id)
        snapshot_pairs = {
            (int(row["from_qu_id"]), int(row["to_qu_id"])): row
            for row in conversions
            if int(row.get("product_id") or 0) == product_id
        }
        current_pairs = {
            (int(row["from_qu_id"]), int(row["to_qu_id"])): row
            for row in current_conversions
            if int(row.get("product_id") or 0) == product_id
        }

        for pair, row in current_pairs.items():
            if pair not in snapshot_pairs:
                await self.delete_quantity_unit_conversion(int(row["id"]))

        for pair, row in snapshot_pairs.items():
            payload = {
                "from_qu_id": int(row["from_qu_id"]),
                "to_qu_id": int(row["to_qu_id"]),
                "factor": row["factor"],
                "product_id": product_id,
            }
            if pair in current_pairs:
                await self.update_quantity_unit_conversion(int(current_pairs[pair]["id"]), payload)
            else:
                await self.create_quantity_unit_conversion(payload)

    @staticmethod
    def product_payload(product: PendingProductConfirmation, picture_file_name: str | None = None) -> dict:
        description = product.description or ""
        if product.brand:
            description = f"{description}\nBrand: {product.brand}".strip()
        if product.quantity:
            description = f"{description}\nQuantity: {product.quantity}".strip()
        payload = {
            "name": product.name,
            "description": description or None,
            "location_id": product.location_id,
            "qu_id_purchase": product.qu_id_purchase,
            "qu_id_stock": product.qu_id_stock,
            "qu_id_consume": product.qu_id_stock,
            "qu_id_price": product.qu_id_purchase,
        }
        if picture_file_name:
            payload["picture_file_name"] = picture_file_name
        return payload

    @staticmethod
    def product_object_payload(product: dict) -> dict:
        payload = {
            "name": product["name"],
            "description": product.get("description"),
            "location_id": product["location_id"],
            "qu_id_purchase": product["qu_id_purchase"],
            "qu_id_stock": product["qu_id_stock"],
            "qu_id_consume": product["qu_id_consume"],
            "qu_id_price": product["qu_id_price"],
        }
        if product.get("picture_file_name"):
            payload["picture_file_name"] = product["picture_file_name"]
        return payload

    async def dashboard_products(self) -> list[dict]:
        products = await self.get_objects("products")
        result = []
        for product in products:
            details = await self.product_details(int(product["id"]))
            result.append(self.product_card(details))
        return result

    def product_card(self, details: dict) -> dict:
        product = details["product"]
        picture = product.get("picture_file_name")
        image_url = None
        if picture:
            encoded = base64.b64encode(picture.encode()).decode()
            image_url = (
                f"{settings.grocy_public_url.rstrip('/')}/api/files/productpictures/{encoded}"
                "?force_serve_as=picture&best_fit_width=640"
            )
        return {
            "product_id": product["id"],
            "name": product["name"],
            "description": product.get("description"),
            "location_id": product.get("location_id"),
            "qu_id_purchase": product.get("qu_id_purchase"),
            "qu_id_stock": product.get("qu_id_stock"),
            "image_url": image_url,
            "stock_amount": details.get("stock_amount", 0),
            "quantity_unit": (details.get("quantity_unit_stock") or {}).get("name"),
            "location": (details.get("location") or {}).get("name"),
            "barcodes": [item.get("barcode") for item in details.get("product_barcodes", [])],
        }

    async def _upload_product_picture(self, barcode: str, image_url: HttpUrl | None) -> str | None:
        if image_url is None:
            return None
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(str(image_url))
        if response.status_code != 200:
            return None
        file_name = self.picture_file_name(barcode, str(image_url))
        encoded = base64.b64encode(file_name.encode()).decode()
        await self._request(
            "PUT",
            f"/files/productpictures/{encoded}",
            content=response.content,
            headers={"Content-Type": response.headers.get("content-type", "application/octet-stream")},
        )
        return file_name

    @staticmethod
    def picture_file_name(barcode: str, image_url: str) -> str:
        suffix = Path(urlparse(image_url).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".jpg"
        return f"{barcode}-{uuid4().hex[:8]}{suffix}"

    async def _request(self, method: str, path: str, **kwargs):
        headers = {**self.headers(), **kwargs.pop("headers", {})}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("error_message") or response.text
            except ValueError:
                detail = response.text
            raise GrocyError(f"Grocy {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            detail = response.text.strip() or response.headers.get("content-type", "empty response")
            raise GrocyError(f"Grocy returned non-JSON response: {detail[:300]}")
