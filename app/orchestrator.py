import logging

from app.adapters.base import LookupAdapter
from app.adapters.community_catalog import CommunityCatalogAdapter
from app.adapters.open_facts import OpenFactsAdapter
from app.adapters.upcitemdb import UpcItemDbAdapter
from app.adapters.web_search import WebSearchAdapter
from app.agent_search import AgentSearchManager
from app.app_settings import AppSettingsStore
from app.cache import LookupCache
from app.community_catalog import RuntimeCommunityCatalogExporter
from app.config import settings
from app.local_store import LocalProductStore
from app.models import ConfirmedProduct, ConfirmedProductRequest, LookupResponse, LookupResult

logger = logging.getLogger(__name__)


def default_adapters() -> list[LookupAdapter]:
    adapters: list[LookupAdapter] = []
    adapters.append(CommunityCatalogAdapter())
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


def default_community_catalog() -> RuntimeCommunityCatalogExporter:
    return RuntimeCommunityCatalogExporter(AppSettingsStore(settings.app_settings_path))


class LookupOrchestrator:
    def __init__(
        self,
        adapters: list[LookupAdapter] | None = None,
        agent_search: AgentSearchManager | None = None,
        community_catalog=None,
    ) -> None:
        self.adapters = adapters or default_adapters()
        self.cache = LookupCache(settings.lookup_cache_path)
        self.local_store = LocalProductStore(settings.local_products_path)
        self.agent_search = agent_search or AgentSearchManager()
        self.community_catalog = community_catalog or default_community_catalog()

    async def lookup(self, barcode: str, use_cache: bool = True) -> LookupResponse:
        local_product = self.local_store.get(barcode)
        if local_product is not None:
            return LookupResponse(
                barcode=barcode,
                found=True,
                result=self.local_store.to_lookup_result(local_product),
                research_status=self.agent_research_status(barcode),
            )

        if use_cache:
            cached = self.cache.get(barcode)
            if cached:
                return LookupResponse(
                    barcode=barcode,
                    found=True,
                    result=cached,
                    research_status=self.agent_research_status(barcode),
                )

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
            return LookupResponse(
                barcode=barcode,
                found=False,
                research_status=self.agent_research_status(barcode),
            )

        ranked_candidates = sorted(candidates, key=candidate_rank, reverse=True)
        best = ranked_candidates[0]
        best.alternate_names = merge_alternate_names(ranked_candidates, best)
        if best.confidence >= settings.cache_min_confidence and not is_known_non_english(best):
            self.cache.set(best)
        if best.confidence <= settings.agent_search_trigger_confidence or is_known_non_english(best):
            self.agent_search.submit(barcode, fallback_result=best if is_known_non_english(best) else None)
        return LookupResponse(
            barcode=barcode,
            found=True,
            result=best,
            candidates=ranked_candidates[1:],
            research_status=self.agent_research_status(barcode),
        )

    def get_confirmed_product(self, barcode: str) -> ConfirmedProduct | None:
        return self.local_store.get(barcode)

    def confirm_product(self, barcode: str, product: ConfirmedProductRequest) -> ConfirmedProduct:
        confirmed = self.local_store.upsert(barcode, product)
        self.cache.delete(barcode)
        try:
            result = self.community_catalog.export_confirmed_product(barcode, product)
            for warning in result.warnings:
                logger.warning("Community catalog export warning for %s: %s", barcode, warning)
        except Exception as exc:
            logger.warning("Community catalog export failed for %s: %s", barcode, exc)
        return confirmed

    def delete_confirmed_product(self, barcode: str) -> bool:
        return self.local_store.delete(barcode)

    def get_agent_search_status(self, barcode: str) -> dict | None:
        return self.agent_search.store.get_status(barcode)

    def retry_agent_search(self, barcode: str) -> dict | None:
        existing = self.agent_search.store.get_status(barcode)
        fallback = (
            LookupResult.model_validate(existing["fallback"])
            if existing and existing.get("fallback")
            else None
        )
        self.agent_search.store.delete(barcode)
        self.agent_search.submit(barcode, fallback_result=fallback)
        return self.agent_search.store.get_status(barcode)

    def delete_agent_search(self, barcode: str) -> bool:
        return self.agent_search.store.delete(barcode)

    def agent_research_status(self, barcode: str) -> str | None:
        get_status = getattr(self.agent_search.store, "get_status", None)
        if get_status is None:
            return None
        status = get_status(barcode)
        return status["status"] if status else None


def is_known_non_english(result: LookupResult) -> bool:
    return result.name_language not in {None, "", "en"}


def candidate_rank(result: LookupResult) -> tuple[int, float]:
    # Unknown-language sources remain eligible because most retailer APIs omit
    # language metadata. Sourced English names outrank translated English names,
    # and translated names outrank explicitly non-English names.
    if is_known_non_english(result):
        return (0, result.confidence)
    if result.name_origin == "translated":
        return (1, result.confidence)
    return (2, result.confidence)


def merge_alternate_names(candidates: list[LookupResult], selected: LookupResult) -> dict[str, str]:
    alternate_names = dict(selected.alternate_names)
    for candidate in candidates:
        alternate_names.update(candidate.alternate_names)
        if is_known_non_english(candidate) and candidate.name_language:
            alternate_names.setdefault(candidate.name_language, candidate.raw_name or candidate.name)
    alternate_names.pop(selected.name_language or "", None)
    return alternate_names
