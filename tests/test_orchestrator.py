import asyncio

from app.cache import LookupCache
from app.models import LookupResult
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
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "high"
    assert [candidate.source for candidate in response.candidates] == ["low"]
    assert low.calls == ["123"]
    assert high.calls == ["123"]


def test_lookup_uses_cache_without_calling_adapters(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    orchestrator = LookupOrchestrator(adapters=[adapter])
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.cache.set(make_result("cached", 0.95))

    response = run(orchestrator.lookup("123", use_cache=True))

    assert response.found is True
    assert response.result is not None
    assert response.result.source == "cached"
    assert adapter.calls == []


def test_lookup_ignores_stale_cache_without_normalized_name(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    orchestrator = LookupOrchestrator(adapters=[adapter])
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
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
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.found is False
    assert response.result is None
    assert response.candidates == []
