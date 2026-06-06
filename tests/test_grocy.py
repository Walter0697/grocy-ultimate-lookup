import asyncio

from app.grocy import GrocyClient
from app.models import ScanEventRequest


class RecordingGrocyClient(GrocyClient):
    def __init__(self) -> None:
        self.requests = []

    async def _request(self, method: str, path: str, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "GET":
            return {"product": {"id": 4}, "stock_amount": 2}
        return []


def run(coro):
    return asyncio.run(coro)


def event(mode: str) -> ScanEventRequest:
    return ScanEventRequest(
        event_id="event-1",
        device_id="kitchen-pi",
        barcode="123",
        mode=mode,
        quantity=2,
        location_id=9,
    )


def test_stock_operations_forward_location() -> None:
    for mode in ("add", "remove", "set"):
        client = RecordingGrocyClient()
        run(client.apply_stock_operation(4, event(mode)))

        payload = client.requests[0][2]["json"]
        assert payload["location_id"] == 9


def test_picture_file_name_is_unique_per_upload() -> None:
    first = GrocyClient.picture_file_name("066200032500", "https://example.com/image.jpg")
    second = GrocyClient.picture_file_name("066200032500", "https://example.com/image.jpg")

    assert first.startswith("066200032500-")
    assert first.endswith(".jpg")
    assert second.startswith("066200032500-")
    assert second.endswith(".jpg")
    assert first != second
