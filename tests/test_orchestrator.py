import asyncio

from app.cache import LookupCache
from app.community_catalog import CommunityCatalogExporter
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


class FakeAgentStore:
    def __init__(self, result: LookupResult | None = None, status: str | None = None) -> None:
        self.result = result
        self.status = status

    def get_result(self, barcode: str):
        return self.result

    def get_status(self, barcode: str):
        return {"status": self.status} if self.status else None


class FakeAgentSearch:
    def __init__(self, result: LookupResult | None = None) -> None:
        self.store = FakeAgentStore(result)
        self.submitted: list[tuple[str, LookupResult | None]] = []

    def submit(self, barcode: str, fallback_result: LookupResult | None = None) -> bool:
        self.submitted.append((barcode, fallback_result))
        self.store.status = "queued"
        return True


def run(coro):
    return asyncio.run(coro)


def isolate_storage(orchestrator: LookupOrchestrator, tmp_path) -> None:
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))
    orchestrator.agent_search = FakeAgentSearch()


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


def test_lookup_prefers_english_candidate_over_higher_confidence_non_english_candidate(tmp_path) -> None:
    french = make_result("open_products_facts", 0.95)
    french.name = "Sacs à ordures"
    french.raw_name = "Sacs à ordures"
    french.name_language = "fr"
    english = make_result("upcitemdb", 0.9)
    english.name = "Garbage Bags"
    english.raw_name = "Garbage Bags"
    english.name_language = "en"
    orchestrator = LookupOrchestrator(adapters=[FakeAdapter(french), FakeAdapter(english)])
    isolate_storage(orchestrator, tmp_path)

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.name == "Garbage Bags"
    assert response.result.alternate_names == {"fr": "Sacs à ordures"}


def test_lookup_triggers_agent_search_for_non_english_only_result(tmp_path) -> None:
    french = make_result("open_products_facts", 0.95)
    french.name_language = "fr"
    orchestrator = LookupOrchestrator(adapters=[FakeAdapter(french)])
    isolate_storage(orchestrator, tmp_path)

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.name_language == "fr"
    assert orchestrator.agent_search.submitted == [("123", french)]
    assert response.research_status == "queued"


def test_lookup_prefers_sourced_english_over_translation_regardless_of_confidence(tmp_path) -> None:
    sourced = make_result("web_search", 0.4)
    sourced.name = "Sourced English Name"
    sourced.name_language = "en"
    sourced.name_origin = "sourced"
    translated = make_result("agent_translation", 0.55)
    translated.name = "Translated English Name"
    translated.name_language = "en"
    translated.name_origin = "translated"
    orchestrator = LookupOrchestrator(
        adapters=[FakeAdapter(sourced)],
        agent_search=FakeAgentSearch(translated),
    )
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.name == "Sourced English Name"


def test_lookup_prefers_translation_over_non_english_original(tmp_path) -> None:
    french = make_result("open_products_facts", 0.95)
    french.name = "Sacs à ordures"
    french.raw_name = "Sacs à ordures"
    french.name_language = "fr"
    translated = make_result("agent_translation", 0.55)
    translated.name = "Garbage Bags"
    translated.name_language = "en"
    translated.name_origin = "translated"
    translated.alternate_names = {"fr": "Sacs à ordures"}
    orchestrator = LookupOrchestrator(
        adapters=[FakeAdapter(french)],
        agent_search=FakeAgentSearch(translated),
    )
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.name == "Garbage Bags"
    assert response.result.name_origin == "translated"
    assert response.result.alternate_names == {"fr": "Sacs à ordures"}


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


def test_lookup_uses_completed_agent_result_when_external_sources_miss(tmp_path) -> None:
    adapter = FakeAdapter(None)
    agent_result = make_result("agent_search", 0.6)
    orchestrator = LookupOrchestrator(adapters=[adapter], agent_search=FakeAgentSearch(agent_result))
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.source == "agent_search"
    assert adapter.calls == ["123"]


def test_lookup_prefers_trusted_external_result_over_agent_result(tmp_path) -> None:
    adapter = FakeAdapter(make_result("network", 0.9))
    agent_result = make_result("agent_search", 0.6)
    orchestrator = LookupOrchestrator(adapters=[adapter], agent_search=FakeAgentSearch(agent_result))
    orchestrator.cache = LookupCache(str(tmp_path / "cache.sqlite3"))
    orchestrator.local_store = LocalProductStore(str(tmp_path / "local.sqlite3"))

    response = run(orchestrator.lookup("123", use_cache=False))

    assert response.result is not None
    assert response.result.source == "network"
    assert [candidate.source for candidate in response.candidates] == ["agent_search"]


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


def test_confirm_product_exports_user_confirmed_product_to_catalog(tmp_path) -> None:
    orchestrator = LookupOrchestrator(adapters=[])
    isolate_storage(orchestrator, tmp_path)
    catalog_path = tmp_path / "catalog"
    orchestrator.community_catalog = CommunityCatalogExporter(path=catalog_path, enabled=True)

    orchestrator.confirm_product(
        "627985000070",
        ConfirmedProductRequest(name="Manual Product", brand="Manual Brand"),
    )

    product_json = catalog_path / "products" / "627" / "985" / "627985000070" / "product.json"
    assert product_json.exists()


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
    assert orchestrator.agent_search.submitted == [("123", None)]
