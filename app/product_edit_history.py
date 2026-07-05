import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from app.models import (
    ProductEditHistoryBarcodeListResponse,
    ProductEditHistoryBarcodeSummary,
    ProductEditHistoryDetailResponse,
    ProductEditHistoryDiffField,
    ProductEditHistoryEntry,
    ProductEditHistoryListResponse,
)


class ProductEditHistoryStore:
    SORT_COLUMNS = {
        "created_at": "created_at",
        "product_name": "COALESCE(json_extract(after, '$.name'), json_extract(before, '$.name'), '')",
        "barcode": "barcode",
        "product_id": "product_id",
    }
    BARCODE_SORT_COLUMNS = {
        "barcode": "barcode",
        "product_name": "product_name",
        "edit_count": "edit_count",
        "last_edited_at": "last_edited_at",
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
        query: str = "",
    ) -> ProductEditHistoryListResponse:
        sort_column = self.SORT_COLUMNS.get(sort)
        if sort_column is None:
            raise ValueError("Unsupported sort field")
        direction = "ASC" if order == "asc" else "DESC"
        search = query.strip().lower()
        where_clause = ""
        params: list[object] = []
        if search:
            where_clause = """
                WHERE lower(barcode) LIKE ?
                   OR lower(CAST(product_id AS TEXT)) LIKE ?
                   OR lower(COALESCE(json_extract(after, '$.name'), json_extract(before, '$.name'), '')) LIKE ?
                   OR lower(changed_fields) LIKE ?
                   OR lower(before) LIKE ?
                   OR lower(after) LIKE ?
            """
            like = f"%{search}%"
            params.extend([like, like, like, like, like, like])
        with self._connect() as db:
            total = db.execute(
                f"SELECT COUNT(*) AS count FROM product_edit_history {where_clause}",
                params,
            ).fetchone()["count"]
            rows = db.execute(
                f"""
                SELECT *
                FROM product_edit_history
                {where_clause}
                ORDER BY {sort_column} {direction}, id {direction}
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return ProductEditHistoryListResponse(
            items=[self._row(row) for row in rows],
            total=int(total),
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            query=query,
        )

    def detail(self, history_id: int) -> ProductEditHistoryDetailResponse | None:
        entry = self.get(history_id)
        if entry is None:
            return None
        diffs = [
            ProductEditHistoryDiffField(
                field=field,
                before=entry.before.get(field),
                after=entry.after.get(field),
            )
            for field in entry.changed_fields
        ]
        return ProductEditHistoryDetailResponse(entry=entry, diffs=diffs)

    def barcode_summary(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sort: str = "last_edited_at",
        order: str = "desc",
        query: str = "",
    ) -> ProductEditHistoryBarcodeListResponse:
        sort_column = self.BARCODE_SORT_COLUMNS.get(sort)
        if sort_column is None:
            raise ValueError("Unsupported sort field")
        direction = "ASC" if order == "asc" else "DESC"
        search = query.strip().lower()
        where_clause = ""
        params: list[object] = []
        if search:
            where_clause = """
                WHERE lower(barcode) LIKE ?
                   OR lower(product_name) LIKE ?
                   OR lower(CAST(latest_product_id AS TEXT)) LIKE ?
            """
            like = f"%{search}%"
            params.extend([like, like, like])

        base_query = f"""
            WITH ranked AS (
                SELECT
                    barcode,
                    product_id,
                    COALESCE(json_extract(after, '$.name'), json_extract(before, '$.name'), '') AS product_name,
                    created_at,
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY barcode
                        ORDER BY created_at DESC, id DESC
                    ) AS rn,
                    COUNT(*) OVER (PARTITION BY barcode) AS edit_count
                FROM product_edit_history
            )
            SELECT
                barcode,
                COALESCE(
                    (
                        SELECT named.product_name
                        FROM ranked named
                        WHERE named.barcode = ranked.barcode
                          AND named.product_name <> ''
                        ORDER BY named.created_at DESC, named.id DESC
                        LIMIT 1
                    ),
                    product_name
                ) AS product_name,
                product_id AS latest_product_id,
                edit_count,
                created_at AS last_edited_at
            FROM ranked
            WHERE rn = 1
        """
        with self._connect() as db:
            total = db.execute(
                f"SELECT COUNT(*) AS count FROM ({base_query}) summary {where_clause}",
                params,
            ).fetchone()["count"]
            rows = db.execute(
                f"""
                SELECT *
                FROM ({base_query}) summary
                {where_clause}
                ORDER BY {sort_column} {direction}, barcode {direction}
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return ProductEditHistoryBarcodeListResponse(
            items=[ProductEditHistoryBarcodeSummary.model_validate(dict(row)) for row in rows],
            total=int(total),
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            query=query,
        )

    def _row(self, row: sqlite3.Row) -> ProductEditHistoryEntry:
        result = dict(row)
        result["changed_fields"] = json.loads(result["changed_fields"])
        result["before"] = json.loads(result["before"])
        result["after"] = json.loads(result["after"])
        return ProductEditHistoryEntry.model_validate(result)
