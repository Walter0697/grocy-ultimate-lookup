import os
from pathlib import Path


TEST_DATA_DIR = Path("/tmp/grocy-ultimate-lookup-tests")
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "LOOKUP_CACHE_PATH": str(TEST_DATA_DIR / "lookup-cache.sqlite3"),
        "LOCAL_PRODUCTS_PATH": str(TEST_DATA_DIR / "local-products.sqlite3"),
        "AUTO_CREATED_PRODUCTS_PATH": str(TEST_DATA_DIR / "auto-created-products.sqlite3"),
        "AGENT_SEARCH_PATH": str(TEST_DATA_DIR / "agent-search.sqlite3"),
        "SCAN_EVENTS_PATH": str(TEST_DATA_DIR / "scan-events.sqlite3"),
        "APP_SETTINGS_PATH": str(TEST_DATA_DIR / "app-settings.sqlite3"),
        "UPLOADED_IMAGES_PATH": str(TEST_DATA_DIR / "uploaded-images"),
        "UPLOADED_IMAGES_BASE_URL": "http://lookup.test/uploaded-images",
        "COMMUNITY_CATALOG_PATH": str(TEST_DATA_DIR / "community-catalog"),
        "COMMUNITY_CATALOG_QUEUE_PATH": str(TEST_DATA_DIR / "community-catalog-queue.sqlite3"),
        "COMMUNITY_CATALOG_WORKDIR": str(TEST_DATA_DIR / "community-catalog-workdir"),
        "SCANNER_DEVICE_TOKENS": "",
    }
)
