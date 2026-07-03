import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from app.models import ProductEditHistoryEntry, ProductEditHistoryListResponse


class ProductEditHistoryStore:
    SORT_COLUMNS = {
        "created_at": "created_at",
        "product_name": "COALESCE(json_extract(after, '$.name'), json_extract(before, '$.name'), '')",
        "barcode": "barcode",
        "product_id": "product_id",
    }

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
                CREATE TABLE IF NOT EXISTS product_edit_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    barcode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    changed_fields TEXT NOT NULL,
                    before TEXT NOT NULL,
                    after TEXT NOT NULL,
                    related_event_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def create(
        self,
        *,
        product_id: int,
        barcode: str,
        source: str,
        changed_fields: list[str],
        before: dict,
        after: dict,
        related_event_id: str | None = None,
    ) -> ProductEditHistoryEntry:
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT INTO product_edit_history (
                    product_id,
                    barcode,
                    source,
                    changed_fields,
                    before,
                    after,
                    related_event_id,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_id,
                    barcode,
                    source,
                    json.dumps(changed_fields),
                    json.dumps(before),
                    json.dumps(after),
                    related_event_id,
                    created_at,
                ),
            )
        record = self.get(cursor.lastrowid)
        if record is None:
            raise RuntimeError("Failed to save product edit history")
        return record

    def get(self, history_id: int) -> ProductEditHistoryEntry | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM product_edit_history WHERE id = ?",
                (history_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row(row)

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str = "created_at",
        order: str = "desc",
    ) -> ProductEditHistoryListResponse:
        sort_column = self.SORT_COLUMNS.get(sort)
        if sort_column is None:
            raise ValueError("Unsupported sort field")
        direction = "ASC" if order == "asc" else "DESC"
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) AS count FROM product_edit_history").fetchone()["count"]
            rows = db.execute(
                f"""
                SELECT *
                FROM product_edit_history
                ORDER BY {sort_column} {direction}, id {direction}
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return ProductEditHistoryListResponse(
            items=[self._row(row) for row in rows],
            total=int(total),
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
        )

    def _row(self, row: sqlite3.Row) -> ProductEditHistoryEntry:
        result = dict(row)
        result["changed_fields"] = json.loads(result["changed_fields"])
        result["before"] = json.loads(result["before"])
        result["after"] = json.loads(result["after"])
        return ProductEditHistoryEntry.model_validate(result)
