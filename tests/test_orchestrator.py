import asyncio

from app.cache import LookupCache
from app.local_store import LocalProductStore
from app.models import ConfirmedProductRequest, LookupResult
from app.orchestrator import LookupOrchestrator


class FakeAdapter:
    def __init__(self, result: LookupResult | None) -> None:
        self.result = result
        self.calls: list[str] = []

    async def lookup(self, barcode: str) -> LookupResult | None:
        self.calls.append(barcode)
        return self.result


def run(coro):
    return asyncio.run(coro)


def isolate_storage(orchestrator: LookupOrchestrator, tmp_path) -> None:
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))


def make_result(source: str, confidence: float) -> LookupResult:
    return LookupResult(
        barcode="123",
        name=f"{source} product",
        normalized_name=f"{source} product",
        source=source,
        confidence=confidence,
    )


def test_lookup_returns_highest_confidence_candidate(tmp_path) -> None:
    low = FakeAdapter(make_result("low", 0.4))
    high = FakeAdapter(make_result("high", 0.9))
    orchestrator = LookupOrchestrator(adapters=[low, high])
    isolate_storage(orchestrator, tmp_path)

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "high"
    assert [candidate.source for candidate in response.candidates] == ["low"]
    assert low.calls == ["123"]
    assert high.calls == ["123"]


def test_lookup_prefers_local_confirmed_product_over_external_sources(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    orchestrator = LookupOrchestrator(adapters=[adapter])
    isolate_storage(orchestrator, tmp_path)
    orchestrator.confirm_product(
        "123",
        ConfirmedProductRequest(
            name="My Confirmed Product",
            brand="Home",
            size="12 oz",
            notes="corrected by user",
        ),
    )

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is True
    assert response.result is not None
    assert response.result.name == "My Confirmed Product"
    assert response.result.source == "local_confirmed"
    assert response.result.confidence == 1.0
    assert response.result.brand == "Home"
    assert response.result.size == "12 oz"
    assert adapter.calls == []


def test_confirm_product_updates_existing_local_match(tmp_path) -> None:
    orchestrator = LookupOrchestrator(adapters=[])
    isolate_storage(orchestrator, tmp_path)
    orchestrator.confirm_product("123", ConfirmedProductRequest(name="Old Name"))

    updated = orchestrator.confirm_product("123", ConfirmedProductRequest(name="New Name", variant="Vanilla"))

    assert updated.user_product_name == "New Name"
    assert updated.variant == "Vanilla"
    response = run(orchestrator.lookup("123"))
    assert response.result is not None
    assert response.result.name == "New Name"
    assert response.result.variant == "Vanilla"


def test_confirm_product_clears_external_cache_for_same_barcode(tmp_path) -> None:
    adapter = FakeAdapter(None)
    orchestrator = LookupOrchestrator(adapters=[adapter])
    isolate_storage(orchestrator, tmp_path)
    orchestrator.cache.set(make_result("cached", 0.95))

    orchestrator.confirm_product("123", ConfirmedProductRequest(name="Confirmed Name"))
    response = run(orchestrator.lookup("123", use_cache=True))

    assert response.result is not None
    assert response.result.source == "local_confirmed"
    assert response.result.name == "Confirmed Name"
    assert adapter.calls == []


def test_lookup_uses_cache_without_calling_adapters(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    orchestrator = LookupOrchestrator(adapters=[adapter])
    isolate_storage(orchestrator, tmp_path)
    orchestrator.cache.set(make_result("cached", 0.95))

    response = run(orchestrator.lookup("123", use_cache=True))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "cached"
    assert adapter.calls == []


def test_lookup_ignores_stale_cache_without_normalized_name(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    orchestrator = LookupOrchestrator(adapters=[adapter])
    isolate_storage(orchestrator, tmp_path)
    orchestrator.cache.set(
        LookupResult(
            barcode="123",
            name="stale product",
            source="stale",
            confidence=0.95,
        )
    )

    response = run(orchestrator.lookup("123", use_cache=True))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "network"
    assert adapter.calls == ["123"]


def test_lookup_returns_not_found_when_all_adapters_miss(tmp_path) -> None:
    adapter = FakeAdapter(None)
    orchestrator = LookupOrchestrator(adapters=[adapter])
    isolate_storage(orchestrator, tmp_path)

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is False
    assert response.result is None
    assert response.candidates == []
