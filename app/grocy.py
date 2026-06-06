import base64
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

    async def get_objects(self, entity: str) -> list[dict]:
        return await self._request("GET", f"/objects/{entity}")

    async def apply_stock_operation(self, product_id: int, event: ScanEventRequest) -> dict:
        if event.mode == "add":
            payload = {"amount": event.quantity, "transaction_type": "purchase", "note": event.event_id}
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
        description = product.description or ""
        if product.brand:
            description = f"{description}\nBrand: {product.brand}".strip()
        if product.quantity:
            description = f"{description}\nQuantity: {product.quantity}".strip()
        payload = {
            "name": product.name,
            "description": description or None,
            "location_id": product.location_id,
            "qu_id_purchase": product.qu_id,
            "qu_id_stock": product.qu_id,
            "qu_id_consume": product.qu_id,
            "qu_id_price": product.qu_id,
        }
        if picture_file_name:
            payload["picture_file_name"] = picture_file_name
        created = await self._request("POST", "/objects/products", json=payload)
        product_id = int(created["created_object_id"])
        await self._request(
            "POST",
            "/objects/product_barcodes",
            json={"product_id": product_id, "barcode": barcode, "qu_id": product.qu_id},
        )
        return await self.product_details(product_id)

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
        return response.json()
