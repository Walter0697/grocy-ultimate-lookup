from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.community_catalog import catalog_product_dir, sanitize_barcode
from app.models import ConfirmedProductRequest


class CommunityCatalogQueue:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_catalog_products (
                    barcode TEXT PRIMARY KEY,
                    product_json TEXT NOT NULL,
                    local_image_path TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert(self, barcode: str, product: ConfirmedProductRequest, *, local_image_path: str | None = None) -> None:
        safe_barcode = sanitize_barcode(barcode)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO pending_catalog_products (barcode, product_json, local_image_path)
                VALUES (?, ?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    product_json = excluded.product_json,
                    local_image_path = excluded.local_image_path,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (safe_barcode, product.model_dump_json(), local_image_path),
            )

    def list(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT barcode, product_json, local_image_path, created_at, updated_at
                FROM pending_catalog_products
                ORDER BY updated_at DESC, barcode ASC
                """
            ).fetchall()
        return [self._row_to_pending(row) for row in rows]

    def selected(self, barcodes: list[str]) -> list[dict]:
        selected = {sanitize_barcode(barcode) for barcode in barcodes}
        return [item for item in self.list() if item["barcode"] in selected]

    def delete(self, barcodes: list[str]) -> None:
        selected = [sanitize_barcode(barcode) for barcode in barcodes]
        if not selected:
            return
        placeholders = ",".join("?" for _ in selected)
        with self._connect() as db:
            db.execute(f"DELETE FROM pending_catalog_products WHERE barcode IN ({placeholders})", selected)

    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM pending_catalog_products")

    @staticmethod
    def _row_to_pending(row: sqlite3.Row) -> dict:
        product = ConfirmedProductRequest.model_validate(json.loads(row["product_json"]))
        product_dir = catalog_product_dir(row["barcode"])
        has_image = bool(row["local_image_path"] or product.image_url)
        files = [f"{product_dir.as_posix()}/product.json"]
        if has_image:
            files.append(f"{product_dir.as_posix()}/image.jpg")
        return {
            "barcode": row["barcode"],
            "path": product_dir.as_posix(),
            "name": product.name,
            "brand": product.brand,
            "quantity": product.quantity or product.size,
            "has_image": has_image,
            "files": files,
            "product": product,
            "local_image_path": row["local_image_path"],
        }
