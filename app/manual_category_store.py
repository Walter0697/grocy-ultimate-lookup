import sqlite3
from pathlib import Path
from uuid import uuid4


class ManualCategoryStore:
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
                CREATE TABLE IF NOT EXISTS manual_categories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    emoji TEXT,
                    image_url TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_category_items (
                    id TEXT PRIMARY KEY,
                    category_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    default_location TEXT NOT NULL,
                    note TEXT,
                    emoji TEXT,
                    image_url TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_manual_category_items_category_id
                ON manual_category_items (category_id)
                """
            )

    def list_categories(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, name, group_name, emoji, image_url, created_at
                FROM manual_categories
                ORDER BY created_at ASC, name ASC
                """
            ).fetchall()
        return [self._to_category(row) for row in rows]

    def get_category(self, category_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT id, name, group_name, emoji, image_url, created_at
                FROM manual_categories
                WHERE id = ?
                """,
                (category_id,),
            ).fetchone()
        return self._to_category(row) if row else None

    def list_items(self, category_id: str | None = None) -> list[dict]:
        query = """
            SELECT id, category_id, name, quantity, unit, default_location, note, emoji, image_url, favorite, created_at
            FROM manual_category_items
        """
        params: tuple[str, ...] = ()
        if category_id is not None:
            query += " WHERE category_id = ?"
            params = (category_id,)
        query += " ORDER BY created_at ASC, name ASC"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._to_item(row) for row in rows]

    def category_exists(self, category_id: str) -> bool:
        with self._connect() as db:
            custom = db.execute(
                "SELECT 1 FROM manual_categories WHERE id = ?",
                (category_id,),
            ).fetchone()
        return custom is not None

    def create_category(
        self,
        *,
        name: str,
        group: str,
        emoji: str | None = None,
        image_url: str | None = None,
    ) -> dict:
        category_id = f"custom-{uuid4().hex[:12]}"
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO manual_categories (id, name, group_name, emoji, image_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (category_id, name.strip(), group, emoji, image_url),
            )
            row = db.execute(
                """
                SELECT id, name, group_name, emoji, image_url, created_at
                FROM manual_categories
                WHERE id = ?
                """,
                (category_id,),
            ).fetchone()
        return self._to_category(row)

    def create_item(
        self,
        *,
        category_id: str,
        name: str,
        quantity: str,
        unit: str,
        default_location: str,
        note: str | None = None,
        emoji: str | None = None,
        image_url: str | None = None,
        favorite: bool = False,
    ) -> dict:
        item_id = f"custom-item-{uuid4().hex[:12]}"
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO manual_category_items (
                    id, category_id, name, quantity, unit, default_location, note, emoji, image_url, favorite
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    category_id,
                    name.strip(),
                    quantity.strip(),
                    unit.strip(),
                    default_location.strip(),
                    note,
                    emoji,
                    image_url,
                    1 if favorite else 0,
                ),
            )
            row = db.execute(
                """
                SELECT id, category_id, name, quantity, unit, default_location, note, emoji, image_url, favorite, created_at
                FROM manual_category_items
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
        return self._to_item(row)

    def _to_category(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "group": row["group_name"],
            "emoji": row["emoji"],
            "image_url": row["image_url"],
            "custom": True,
            "variants": [],
        }

    def _to_item(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "category_id": row["category_id"],
            "name": row["name"],
            "quantity": row["quantity"],
            "unit": row["unit"],
            "default_location": row["default_location"],
            "note": row["note"],
            "emoji": row["emoji"],
            "image_url": row["image_url"],
            "favorite": bool(row["favorite"]),
            "custom": True,
        }
