import sqlite3
from pathlib import Path

from app.models import ConfirmedProduct, ConfirmedProductRequest, LookupResult
from app.normalization import normalize_product_name


class LocalProductStore:
    def __init__(self, path: str) -> None:
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
                CREATE TABLE IF NOT EXISTS local_products (
                    barcode TEXT PRIMARY KEY,
                    user_product_name TEXT NOT NULL,
                    brand TEXT,
                    quantity TEXT,
                    size TEXT,
                    count INTEGER,
                    variant TEXT,
                    image_url TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, barcode: str) -> ConfirmedProduct | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM local_products WHERE barcode = ?", (barcode,)).fetchone()
        if row is None:
            return None
        return self._row_to_confirmed_product(row)

    def upsert(self, barcode: str, product: ConfirmedProductRequest) -> ConfirmedProduct:
        image_url = str(product.image_url) if product.image_url is not None else None
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO local_products (
                    barcode,
                    user_product_name,
                    brand,
                    quantity,
                    size,
                    count,
                    variant,
                    image_url,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(barcode) DO UPDATE SET
                    user_product_name = excluded.user_product_name,
                    brand = excluded.brand,
                    quantity = excluded.quantity,
                    size = excluded.size,
                    count = excluded.count,
                    variant = excluded.variant,
                    image_url = excluded.image_url,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    barcode,
                    product.name.strip(),
                    product.brand,
                    product.quantity,
                    product.size,
                    product.count,
                    product.variant,
                    image_url,
                    product.notes,
                ),
            )
        confirmed = self.get(barcode)
        if confirmed is None:
            raise RuntimeError("Failed to save local product")
        return confirmed

    def delete(self, barcode: str) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM local_products WHERE barcode = ?", (barcode,))
            return cursor.rowcount > 0

    def to_lookup_result(self, product: ConfirmedProduct) -> LookupResult:
        normalized = normalize_product_name(
            raw_name=product.user_product_name,
            brand=product.brand,
            quantity=product.quantity,
        )
        return LookupResult(
            barcode=product.barcode,
            name=product.user_product_name,
            raw_name=product.user_product_name,
            normalized_name=normalized.normalized_name,
            brand=normalized.brand,
            quantity=product.quantity,
            size=product.size or normalized.size,
            count=product.count or normalized.count,
            variant=product.variant or normalized.variant,
            image_url=product.image_url,
            source="local_confirmed",
            confidence=1.0,
            raw_payload={"confirmed_product": product.model_dump(mode="json")},
        )

    def _row_to_confirmed_product(self, row: sqlite3.Row) -> ConfirmedProduct:
        return ConfirmedProduct(
            barcode=row["barcode"],
            user_product_name=row["user_product_name"],
            brand=row["brand"],
            quantity=row["quantity"],
            size=row["size"],
            count=row["count"],
            variant=row["variant"],
            image_url=row["image_url"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
