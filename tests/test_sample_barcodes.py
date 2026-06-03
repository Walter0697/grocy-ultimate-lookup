import asyncio
import pytest

from app.cache import LookupCache
from app.local_store import LocalProductStore
from app.models import LookupResult
from app.orchestrator import LookupOrchestrator


SAMPLE_EXPECTATIONS = {
    "810669032478": None,
    "761720097809": ("open_food_facts", "Corn Starch"),
    "059631755520": ("upcitemdb", "Lysol 2058 Disinfecting Wipes - Citrus"),
    "057000013165": ("open_food_facts", "Tomato Ketchup"),
    "030772191224": (
        "upcitemdb",
        "Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent",
    ),
    "067489302124": None,
}


class SampleBarcodeAdapter:
    def __init__(self, source: str, results: dict[str, LookupResult]) -> None:
        self.source = source
        self.results = results

    async def lookup(self, barcode: str) -> LookupResult | None:
        return self.results.get(barcode)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(("barcode", "expected"), SAMPLE_EXPECTATIONS.items())
def test_sample_barcode_outcomes(barcode, expected, tmp_path) -> None:
    orchestrator = LookupOrchestrator(
        adapters=[
            SampleBarcodeAdapter(
                "open_food_facts",
                {
                    "761720097809": LookupResult(
                        barcode="761720097809",
                        name="Corn Starch",
                        normalized_name="Corn Starch",
                        raw_name="Corn Starch",
                        source="open_food_facts",
                        confidence=0.95,
                    ),
                    "057000013165": LookupResult(
                        barcode="057000013165",
                        name="Tomato Ketchup",
                        normalized_name="Tomato Ketchup",
                        raw_name="Tomato Ketchup",
                        source="open_food_facts",
                        confidence=0.95,
                    ),
                },
            ),
            SampleBarcodeAdapter(
                "upcitemdb",
                {
                    "059631755520": LookupResult(
                        barcode="059631755520",
                        name="Lysol 2058 Disinfecting Wipes - Citrus",
                        normalized_name="Lysol 2058 Disinfecting Wipes - Citrus",
                        raw_name="Lysol 2058 Disinfecting Wipes - Citrus  Case Of 12",
                        source="upcitemdb",
                        confidence=0.9,
                    ),
                    "030772191224": LookupResult(
                        barcode="030772191224",
                        name="Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent",
                        normalized_name="Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent",
                        raw_name="Gain Moonlight Breeze HE Deep Cleaning Concentrated Liquid Laundry Detergent 100 Loads - 144 fl oz",
                        source="upcitemdb",
                        confidence=0.9,
                    ),
                },
            ),
        ]
    )
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    response = run(orchestrator.lookup(barcode, use_cache=False))

    if expected is None:
        assert response.found is False
        assert response.result is None
    else:
        expected_source, expected_name = expected
        assert response.found is True
        assert response.result is not None
        assert response.result.source == expected_source
        assert response.result.normalized_name == expected_name
