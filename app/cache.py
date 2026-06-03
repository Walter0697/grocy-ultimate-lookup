import json
import sqlite3
from pathlib import Path

from app.models import LookupResult


class LookupCache:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS lookup_cache (
                    barcode TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, barcode: str) -> LookupResult | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM lookup_cache WHERE barcode = ?", (barcode,)).fetchone()
        if row is None:
            return None
        return LookupResult.model_validate_json(row[0])

    def set(self, result: LookupResult) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO lookup_cache (barcode, payload)
                VALUES (?, ?)
                ON CONFLICT(barcode) DO UPDATE SET payload = excluded.payload
                """,
                (result.barcode, json.dumps(result.model_dump(mode="json"))),
            )
