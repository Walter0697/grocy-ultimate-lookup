import pytest
from pydantic import ValidationError

from app.models import LookupResult, ScanEventRequest


def test_lookup_result_accepts_minimal_product() -> None:
    result = LookupResult(
        barcode="057000013165",
        name="Heinz Tomato Ketchup",
        normalized_name="Heinz Tomato Ketchup",
        source="test",
        confidence=0.9,
    )

    assert result.barcode == "057000013165"
    assert result.name == "Heinz Tomato Ketchup"
    assert result.normalized_name == "Heinz Tomato Ketchup"


def test_set_scan_allows_zero_but_add_does_not() -> None:
    set_event = ScanEventRequest(event_id="1", device_id="pi", barcode="123", mode="set", quantity=0)
    assert set_event.quantity == 0

    with pytest.raises(ValidationError):
        ScanEventRequest(event_id="2", device_id="pi", barcode="123", mode="add", quantity=0)
