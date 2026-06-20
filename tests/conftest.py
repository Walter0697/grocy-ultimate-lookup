import os
from pathlib import Path


TEST_DATA_DIR = Path("/tmp/grocy-ultimate-lookup-tests")
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("LOOKUP_CACHE_PATH", str(TEST_DATA_DIR / "lookup-cache.sqlite3"))
os.environ.setdefault("LOCAL_PRODUCTS_PATH", str(TEST_DATA_DIR / "local-products.sqlite3"))
os.environ.setdefault("AGENT_SEARCH_PATH", str(TEST_DATA_DIR / "agent-search.sqlite3"))
os.environ.setdefault("SCAN_EVENTS_PATH", str(TEST_DATA_DIR / "scan-events.sqlite3"))
os.environ.setdefault("UPLOADED_IMAGES_PATH", str(TEST_DATA_DIR / "uploaded-images"))
os.environ.setdefault("UPLOADED_IMAGES_BASE_URL", "http://lookup.test/uploaded-images")
os.environ.setdefault("SCANNER_DEVICE_TOKENS", "")
