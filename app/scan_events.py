import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import ScanEventRequest


class ScanEventStore:
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
                CREATE TABLE IF NOT EXISTS scan_events (
                    event_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    barcode TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    location_id INTEGER,
                    status TEXT NOT NULL,
                    product_id INTEGER,
                    product_name TEXT,
                    image_url TEXT,
                    stock_before REAL,
                    stock_after REAL,
                    lookup_payload TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(scan_events)")}
            if "location_id" not in columns:
                db.execute("ALTER TABLE scan_events ADD COLUMN location_id INTEGER")

    def create(self, event: ScanEventRequest) -> tuple[dict, bool]:
        existing = self.get(event.event_id)
        if existing:
            return existing, False
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO scan_events (event_id, device_id, barcode, mode, quantity, location_id, status)
                VALUES (?, ?, ?, ?, ?, ?, 'processing')
                """,
                (event.event_id, event.device_id, event.barcode, event.mode, event.quantity, event.location_id),
            )
        return self.get(event.event_id), True

    def get(self, event_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM scan_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM scan_events"
        args: list[Any] = []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._connect() as db:
            rows = db.execute(query, args).fetchall()
        return [self._row(row) for row in rows]

    def update(self, event_id: str, **values) -> dict:
        allowed = {
            "status",
            "product_id",
            "product_name",
            "image_url",
            "stock_before",
            "stock_after",
            "lookup_payload",
            "error",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if "lookup_payload" in updates and not isinstance(updates["lookup_payload"], str):
            updates["lookup_payload"] = json.dumps(updates["lookup_payload"])
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as db:
            db.execute(
                f"UPDATE scan_events SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE event_id = ?",
                [*updates.values(), event_id],
            )
        result = self.get(event_id)
        if result is None:
            raise RuntimeError("Scan event disappeared")
        return result

    def _row(self, row: sqlite3.Row) -> dict:
        result = dict(row)
        result["lookup_payload"] = json.loads(result["lookup_payload"]) if result["lookup_payload"] else None
        return result
