from app.adapters.base import LookupAdapter
from app.adapters.open_facts import OpenFactsAdapter
from app.adapters.upcitemdb import UpcItemDbAdapter
from app.adapters.web_search import WebSearchAdapter
from app.agent_search import AgentSearchManager
from app.cache import LookupCache
from app.config import settings
from app.local_store import LocalProductStore
from app.models import ConfirmedProduct, ConfirmedProductRequest, LookupResponse, LookupResult


def default_adapters() -> list[LookupAdapter]:
    adapters: list[LookupAdapter] = []
    if settings.enable_open_facts:
        adapters.extend(
            [
                OpenFactsAdapter("open_food_facts", "world.openfoodfacts.org"),
                OpenFactsAdapter("open_products_facts", "world.openproductsfacts.org"),
                OpenFactsAdapter("open_beauty_facts", "world.openbeautyfacts.org"),
                OpenFactsAdapter("open_pet_food_facts", "world.openpetfoodfacts.org"),
            ]
        )
    if settings.enable_upcitemdb:
        adapters.append(UpcItemDbAdapter())
    if settings.enable_web_search:
        adapters.append(WebSearchAdapter())
    return adapters


class LookupOrchestrator:
    def __init__(
        self,
        adapters: list[LookupAdapter] | None = None,
        agent_search: AgentSearchManager | None = None,
    ) -> None:
        self.adapters = adapters or default_adapters()
        self.cache = LookupCache(settings.lookup_cache_path)
        self.local_store = LocalProductStore(settings.local_products_path)
        self.agent_search = agent_search or AgentSearchManager()

    async def lookup(self, barcode: str, use_cache: bool = True) -> LookupResponse:
        local_product = self.local_store.get(barcode)
        if local_product is not None:
            return LookupResponse(
                barcode=barcode,
                found=True,
                result=self.local_store.to_lookup_result(local_product),
            )

        if use_cache:
            cached = self.cache.get(barcode)
            if cached:
                return LookupResponse(barcode=barcode, found=True, result=cached)

        candidates: list[LookupResult] = []
        agent_result = self.agent_search.store.get_result(barcode)
        if agent_result is not None:
            candidates.append(agent_result)
        for adapter in self.adapters:
            result = await adapter.lookup(barcode)
            if result:
                candidates.append(result)

        if not candidates:
            self.agent_search.submit(barcode)
            return LookupResponse(barcode=barcode, found=False)

        ranked_candidates = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        best = ranked_candidates[0]
        if best.confidence >= settings.cache_min_confidence:
            self.cache.set(best)
        if best.confidence <= settings.agent_search_trigger_confidence:
            self.agent_search.submit(barcode)
        return LookupResponse(barcode=barcode, found=True, result=best, candidates=ranked_candidates[1:])

    def get_confirmed_product(self, barcode: str) -> ConfirmedProduct | None:
        return self.local_store.get(barcode)

    def confirm_product(self, barcode: str, product: ConfirmedProductRequest) -> ConfirmedProduct:
        confirmed = self.local_store.upsert(barcode, product)
        self.cache.delete(barcode)
        return confirmed

    def delete_confirmed_product(self, barcode: str) -> bool:
        return self.local_store.delete(barcode)

    def get_agent_search_status(self, barcode: str) -> dict | None:
        return self.agent_search.store.get_status(barcode)

    def retry_agent_search(self, barcode: str) -> dict | None:
        self.agent_search.store.delete(barcode)
        self.agent_search.submit(barcode)
        return self.agent_search.store.get_status(barcode)

    def delete_agent_search(self, barcode: str) -> bool:
        return self.agent_search.store.delete(barcode)
