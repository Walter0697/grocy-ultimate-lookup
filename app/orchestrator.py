import logging

from app.adapters.base import LookupAdapter
from app.adapters.community_catalog import CommunityCatalogAdapter
from app.adapters.open_facts import OpenFactsAdapter
from app.adapters.upcitemdb import UpcItemDbAdapter
from app.adapters.web_search import WebSearchAdapter, WebSearchLlmFallbackAdapter
from app.agent_search import AgentSearchManager
from app.app_settings import AppSettingsStore, LookupSettings, normalize_lookup_settings
from app.cache import LookupCache
from app.community_catalog import RuntimeCommunityCatalogExporter
from app.config import settings
from app.llm import create_llm_provider
from app.local_store import LocalProductStore
from app.models import ConfirmedProduct, ConfirmedProductRequest, LookupResponse, LookupResult

logger = logging.getLogger(__name__)


def default_adapters(lookup_settings: LookupSettings | None = None) -> list[LookupAdapter]:
    lookup_settings = lookup_settings or AppSettingsStore(settings.app_settings_path).get_lookup()
    lookup_settings = normalize_lookup_settings(lookup_settings)
    adapters: list[LookupAdapter] = []
    for provider in lookup_settings.search_providers:
        if not provider.enabled:
            continue
        adapter = adapter_for_search_provider(provider.id, lookup_settings)
        if adapter is not None:
            adapters.append(adapter)
    return adapters


def default_ai_adapters(lookup_settings: LookupSettings | None = None) -> list[LookupAdapter]:
    lookup_settings = lookup_settings or AppSettingsStore(settings.app_settings_path).get_lookup()
    lookup_settings = normalize_lookup_settings(lookup_settings)
    adapters: list[LookupAdapter] = []
    if lookup_settings.enable_web_search and lookup_settings.enable_llm_fallback:
        llm_provider = create_llm_provider(
            enabled=lookup_settings.enable_llm_fallback,
            base_url=lookup_settings.llm_base_url,
            api_key=lookup_settings.llm_api_key,
            model=lookup_settings.llm_model,
        )
        if llm_provider is not None:
            adapters.append(
                WebSearchLlmFallbackAdapter(
                    search_provider=create_web_search_provider(lookup_settings),
                    llm_provider=llm_provider,
                )
            )
    return adapters


def create_web_search_provider(lookup_settings: LookupSettings):
    from app.search.providers import DuckDuckGoSearchProvider, SearxngSearchProvider

    if lookup_settings.web_search_provider == "searxng" and lookup_settings.searxng_base_url:
        return SearxngSearchProvider(lookup_settings.searxng_base_url)
    return DuckDuckGoSearchProvider()


def adapter_for_search_provider(provider_id: str, lookup_settings: LookupSettings) -> LookupAdapter | None:
    open_facts_hosts = {
        "open_food_facts": "world.openfoodfacts.org",
        "open_products_facts": "world.openproductsfacts.org",
        "open_beauty_facts": "world.openbeautyfacts.org",
        "open_pet_food_facts": "world.openpetfoodfacts.org",
    }
    if provider_id == "community_catalog":
        return CommunityCatalogAdapter()
    if provider_id in open_facts_hosts:
        return OpenFactsAdapter(provider_id, open_facts_hosts[provider_id])
    if provider_id == "upcitemdb":
        return UpcItemDbAdapter()
    if provider_id == "web_search":
        return WebSearchAdapter(search_provider=create_web_search_provider(lookup_settings), llm_provider=None)
    return None


def default_community_catalog() -> RuntimeCommunityCatalogExporter:
    return RuntimeCommunityCatalogExporter(AppSettingsStore(settings.app_settings_path))


class LookupOrchestrator:
    def __init__(
        self,
        adapters: list[LookupAdapter] | None = None,
        ai_adapters: list[LookupAdapter] | None = None,
        agent_search: AgentSearchManager | None = None,
        community_catalog=None,
        settings_store: AppSettingsStore | None = None,
    ) -> None:
        self.adapters = adapters
        self.settings_store = settings_store or AppSettingsStore(settings.app_settings_path)
        if ai_adapters is not None:
            self.ai_adapters = ai_adapters
        elif adapters is None:
            self.ai_adapters = None
        else:
            self.ai_adapters = []
        self.cache = LookupCache(settings.lookup_cache_path)
        self.local_store = LocalProductStore(settings.local_products_path)
        self.agent_search = agent_search or AgentSearchManager()
        self.community_catalog = community_catalog or default_community_catalog()

    async def lookup(self, barcode: str, use_cache: bool = True) -> LookupResponse:
        lookup_settings = normalize_lookup_settings(self.settings_store.get_lookup())
        if self.adapters is None:
            return await self._lookup_configured_order(barcode, lookup_settings, use_cache)

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
        normal_adapters = self.adapters
        ai_adapters = self.ai_adapters if self.ai_adapters is not None else default_ai_adapters(lookup_settings)

        for adapter in normal_adapters:
            result = await adapter.lookup(barcode)
            if result:
                candidates.append(result)

        if candidates:
            best = sorted(candidates, key=candidate_rank, reverse=True)[0]
            if should_defer_ai_fallback(best):
                return self._complete_found_response(barcode, candidates)

        agent_result = self.agent_search.store.get_result(barcode)
        if agent_result is not None:
            candidates.append(agent_result)

        for adapter in ai_adapters:
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

        return self._complete_found_response(barcode, candidates)

    async def _lookup_configured_order(
        self,
        barcode: str,
        lookup_settings: LookupSettings,
        use_cache: bool,
    ) -> LookupResponse:
        candidates: list[LookupResult] = []
        codex_enabled = False

        for provider in lookup_settings.search_providers:
            if not provider.enabled:
                continue

            if provider.id == "grocy_current":
                # Grocy data is resolved by ScannerService before lookup creation.
                continue

            if provider.id == "ultimate_lookup_cache":
                local_product = self.local_store.get(barcode)
                if local_product is not None:
                    return LookupResponse(
                        barcode=barcode,
                        found=True,
                        result=self.local_store.to_lookup_result(local_product),
                        research_status=self.agent_research_status(barcode),
                    )
                if not use_cache:
                    continue
                cached = self.cache.get(barcode)
                if cached:
                    return LookupResponse(
                        barcode=barcode,
                        found=True,
                        result=cached,
                        research_status=self.agent_research_status(barcode),
                    )
                continue

            if provider.id == "agent_completed":
                agent_result = self.agent_search.store.get_result(barcode)
                if agent_result is not None:
                    candidates.append(agent_result)
                    if should_defer_ai_fallback(agent_result):
                        return self._complete_found_response(barcode, candidates)
                continue

            if provider.id == "llm_fallback":
                for adapter in default_ai_adapters(lookup_settings):
                    result = await adapter.lookup(barcode)
                    if result:
                        candidates.append(result)
                        if should_defer_ai_fallback(result):
                            return self._complete_found_response(barcode, candidates)
                continue

            if provider.id == "codex_agent":
                codex_enabled = True
                continue

            adapter = adapter_for_search_provider(provider.id, lookup_settings)
            if adapter is None:
                continue
            result = await adapter.lookup(barcode)
            if result:
                candidates.append(result)
                if should_defer_ai_fallback(result):
                    return self._complete_found_response(barcode, candidates)

        if candidates:
            return self._complete_found_response(barcode, candidates)

        if codex_enabled:
            self.agent_search.submit(barcode)
        return LookupResponse(
            barcode=barcode,
            found=False,
            research_status=self.agent_research_status(barcode),
        )

    def _complete_found_response(self, barcode: str, candidates: list[LookupResult]) -> LookupResponse:
        response = self._found_response(barcode, candidates)
        best = response.result
        if best is None:
            return response
        if best.confidence >= settings.cache_min_confidence and not is_known_non_english(best):
            self.cache.set(best)
        if best.confidence <= settings.agent_search_trigger_confidence or is_known_non_english(best):
            self.agent_search.submit(barcode, fallback_result=best if is_known_non_english(best) else None)
            response.research_status = self.agent_research_status(barcode)
        return response

    def _found_response(self, barcode: str, candidates: list[LookupResult]) -> LookupResponse:
        ranked_candidates = sorted(candidates, key=candidate_rank, reverse=True)
        best = ranked_candidates[0]
        best.alternate_names = merge_alternate_names(ranked_candidates, best)
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


def should_defer_ai_fallback(result: LookupResult) -> bool:
    return result.confidence > settings.agent_search_trigger_confidence and not is_known_non_english(result)


def merge_alternate_names(candidates: list[LookupResult], selected: LookupResult) -> dict[str, str]:
    alternate_names = dict(selected.alternate_names)
    for candidate in candidates:
        alternate_names.update(candidate.alternate_names)
        if is_known_non_english(candidate) and candidate.name_language:
            alternate_names.setdefault(candidate.name_language, candidate.raw_name or candidate.name)
    alternate_names.pop(selected.name_language or "", None)
    return alternate_names
