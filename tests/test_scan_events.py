import sqlite3

from app.models import ScanEventRequest
from app.scan_events import ScanEventStore


def test_store_persists_scan_location(tmp_path) -> None:
    store = ScanEventStore(str(tmp_path / "events.sqlite3"))
    event, created = store.create(
        ScanEventRequest(
            event_id="event-1",
            device_id="kitchen-pi",
            barcode="123",
            mode="add",
            quantity=2,
            location_id=7,
        )
    )

    assert created is True
    assert event["location_id"] == 7


def test_store_migrates_existing_database_with_location_column(tmp_path) -> None:
    path = tmp_path / "events.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE scan_events (
                event_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                barcode TEXT NOT NULL,
                mode TEXT NOT NULL,
                quantity REAL NOT NULL,
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

    ScanEventStore(str(path))

    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(scan_events)")}
    assert "location_id" in columns
