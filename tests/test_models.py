from app.models import LookupResult


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
