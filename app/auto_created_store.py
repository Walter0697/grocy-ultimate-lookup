import sqlite3
from pathlib import Path


class AutoCreatedProductStore:
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
                CREATE TABLE IF NOT EXISTS auto_created_products (
                    product_id INTEGER PRIMARY KEY,
                    barcode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert(self, *, product_id: int, barcode: str, source: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO auto_created_products (product_id, barcode, source)
                VALUES (?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    barcode = excluded.barcode,
                    source = excluded.source,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (product_id, barcode, source),
            )

    def get_by_product_id(self, product_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT product_id, barcode, source FROM auto_created_products WHERE product_id = ?",
                (product_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete(self, product_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM auto_created_products WHERE product_id = ?", (product_id,))
            return cursor.rowcount > 0
