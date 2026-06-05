import pytest
from pydantic import ValidationError

from app.llm import LlmProductExtraction


def test_llm_product_extraction_accepts_normalized_product_json() -> None:
    result = LlmProductExtraction.model_validate(
        {
            "found": True,
            "name": "Extracted Product",
            "brand": "Extracted Brand",
            "quantity": "1 box",
            "size": "12 oz",
            "count": 6,
            "variant": "Original",
            "image_url": "https://example.com/product.jpg",
            "barcode_seen": True,
        }
    )

    assert result.name == "Extracted Product"
    assert result.count == 6
    assert result.barcode_seen is True


def test_llm_product_extraction_rejects_malformed_product_json() -> None:
    with pytest.raises(ValidationError):
        LlmProductExtraction.model_validate(
            {
                "found": True,
                "name": ["not", "a", "string"],
                "count": 0,
                "barcode_seen": "maybe",
            }
        )
