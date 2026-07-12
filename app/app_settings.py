import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import settings

DEFAULT_CATALOG_AUTHOR_NAME = "Grocy Ultimate Lookup Bot"
DEFAULT_CATALOG_AUTHOR_EMAIL = "grocy-ultimate-lookup-bot@example.local"


class CommunityCatalogSettings(BaseModel):
    enabled: bool = False
    repository_url: str | None = None
    github_pat: str | None = None
    branch: str = "main"
    workdir: str = "/data/community-catalog-workdir"
    path: str = "/data/community-catalog"
    export_images: bool = True
    auto_commit: bool = False
    auto_push: bool = True
    auto_push_ai_results: bool = True
    auto_push_modified_products: bool = False
    auto_push_manual_items: bool = False
    git_remote: str = "origin"
    git_branch: str = "main"
    author_name: str | None = None
    author_email: str | None = None


class CommunityCatalogStatus(BaseModel):
    path: str
    repository_url: str | None = None
    branch: str
    path_exists: bool
    is_git_repo: bool
    pending_changes: bool = False
    configured: bool = False


class CommunityCatalogSettingsResponse(BaseModel):
    enabled: bool
    repository_url: str | None
    branch: str
    export_images: bool
    auto_push: bool
    auto_push_ai_results: bool
    auto_push_modified_products: bool
    auto_push_manual_items: bool
    author_name: str | None
    author_email: str | None
    github_pat_set: bool


class CommunityCatalogSettingsUpdate(BaseModel):
    enabled: bool = False
    repository_url: str | None = None
    github_pat: str | None = None
    branch: str = "main"
    export_images: bool = True
    auto_push: bool = True
    auto_push_ai_results: bool = True
    auto_push_modified_products: bool = False
    auto_push_manual_items: bool = False
    author_name: str | None = None
    author_email: str | None = None


class CommunityCatalogMetadata(BaseModel):
    owner: str | None = None
    description: str | None = None
    region: str | None = None
    stores: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class CommunityCatalogDiff(BaseModel):
    configured: bool
    pending_changes: bool
    status: str
    files: list[str] = []


class CommunityCatalogPendingProduct(BaseModel):
    barcode: str
    path: str
    name: str | None = None
    brand: str | None = None
    quantity: str | None = None
    has_image: bool = False
    files: list[str] = []


class CommunityCatalogPendingProducts(BaseModel):
    configured: bool
    pending_changes: bool
    products: list[CommunityCatalogPendingProduct] = []


class CommunityCatalogProductSelection(BaseModel):
    barcodes: list[str] = []


class CommunityCatalogSource(BaseModel):
    id: str | None = None
    name: str | None = None
    repository_url: str
    enabled: bool = True
    priority: int = 0
    owner: str | None = None
    description: str | None = None
    product_count: int | None = None
    validation_status: str | None = None
    validation_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    last_checked: str | None = None
    last_successful_check: str | None = None
    last_failed_check: str | None = None
    last_error: str | None = None


class CommunityCatalogSourceList(BaseModel):
    sources: list[CommunityCatalogSource] = Field(default_factory=list)


DEFAULT_SEARCH_PROVIDER_ORDER = [
    "grocy_current",
    "ultimate_lookup_cache",
    "community_catalog",
    "open_food_facts",
    "open_products_facts",
    "open_beauty_facts",
    "open_pet_food_facts",
    "upcitemdb",
    "web_search",
    "agent_completed",
    "llm_fallback",
    "codex_agent",
]


class SearchProviderSetting(BaseModel):
    id: str
    enabled: bool = True
    priority: int = 0


class LookupSettings(BaseModel):
    enable_open_facts: bool = True
    enable_upcitemdb: bool = True
    enable_web_search: bool = True
    auto_request_missing_images: bool = False
    search_providers: list[SearchProviderSetting] = Field(default_factory=list)
    web_search_provider: str = "duckduckgo"
    searxng_base_url: str | None = None
    enable_llm_fallback: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None


class LookupSettingsResponse(BaseModel):
    enable_open_facts: bool
    enable_upcitemdb: bool
    enable_web_search: bool
    auto_request_missing_images: bool
    search_providers: list[SearchProviderSetting]
    web_search_provider: str
    searxng_base_url: str | None
    enable_llm_fallback: bool
    llm_base_url: str
    llm_model: str | None
    llm_api_key_set: bool


class LookupSettingsUpdate(BaseModel):
    enable_open_facts: bool = True
    enable_upcitemdb: bool = True
    enable_web_search: bool = True
    auto_request_missing_images: bool = False
    search_providers: list[SearchProviderSetting] = []
    web_search_provider: str = "duckduckgo"
    searxng_base_url: str | None = None
    enable_llm_fallback: bool = False
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None


def default_community_catalog_settings() -> CommunityCatalogSettings:
    return CommunityCatalogSettings(
        enabled=settings.community_catalog_enabled,
        repository_url=settings.community_catalog_repository_url,
        github_pat=settings.community_catalog_github_pat,
        branch=settings.community_catalog_git_branch,
        workdir=settings.community_catalog_workdir,
        path=settings.community_catalog_path,
        export_images=settings.community_catalog_export_images,
        auto_commit=settings.community_catalog_auto_commit,
        auto_push=settings.community_catalog_auto_push,
        git_remote=settings.community_catalog_git_remote,
        git_branch=settings.community_catalog_git_branch,
        author_name=settings.community_catalog_author_name or DEFAULT_CATALOG_AUTHOR_NAME,
        author_email=settings.community_catalog_author_email or DEFAULT_CATALOG_AUTHOR_EMAIL,
    )


def default_lookup_settings() -> LookupSettings:
    return normalize_lookup_settings(
        LookupSettings(
            enable_open_facts=settings.enable_open_facts,
            enable_upcitemdb=settings.enable_upcitemdb,
            enable_web_search=settings.enable_web_search,
            auto_request_missing_images=False,
            web_search_provider=settings.web_search_provider,
            searxng_base_url=settings.searxng_base_url,
            enable_llm_fallback=settings.enable_llm_fallback,
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
        )
    )


def public_community_catalog_settings(settings_value: CommunityCatalogSettings) -> CommunityCatalogSettingsResponse:
    return CommunityCatalogSettingsResponse(
        enabled=settings_value.enabled,
        repository_url=settings_value.repository_url,
        branch=settings_value.branch or settings_value.git_branch,
        export_images=settings_value.export_images,
        auto_push=settings_value.auto_push,
        auto_push_ai_results=settings_value.auto_push_ai_results,
        auto_push_modified_products=settings_value.auto_push_modified_products,
        auto_push_manual_items=settings_value.auto_push_manual_items,
        author_name=settings_value.author_name,
        author_email=settings_value.author_email,
        github_pat_set=bool(settings_value.github_pat),
    )


def public_lookup_settings(settings_value: LookupSettings) -> LookupSettingsResponse:
    settings_value = normalize_lookup_settings(settings_value)
    return LookupSettingsResponse(
        enable_open_facts=settings_value.enable_open_facts,
        enable_upcitemdb=settings_value.enable_upcitemdb,
        enable_web_search=settings_value.enable_web_search,
        auto_request_missing_images=settings_value.auto_request_missing_images,
        search_providers=settings_value.search_providers,
        web_search_provider=settings_value.web_search_provider,
        searxng_base_url=settings_value.searxng_base_url,
        enable_llm_fallback=settings_value.enable_llm_fallback,
        llm_base_url=settings_value.llm_base_url,
        llm_model=settings_value.llm_model,
        llm_api_key_set=bool(settings_value.llm_api_key),
    )


def normalize_lookup_settings(value: LookupSettings) -> LookupSettings:
    known_ids = set(DEFAULT_SEARCH_PROVIDER_ORDER)
    enabled_by_id = {provider.id: provider.enabled for provider in value.search_providers if provider.id in known_ids}
    if not value.search_providers:
        for provider_id in DEFAULT_SEARCH_PROVIDER_ORDER:
            enabled_by_id[provider_id] = default_search_provider_enabled(provider_id, value)

    ordered: list[str] = []
    seen: set[str] = set()
    for provider in sorted(value.search_providers, key=lambda item: item.priority):
        if provider.id in known_ids and provider.id not in seen:
            ordered.append(provider.id)
            seen.add(provider.id)
    for provider_id in DEFAULT_SEARCH_PROVIDER_ORDER:
        if provider_id not in seen:
            ordered.append(provider_id)

    normalized = [
        SearchProviderSetting(
            id=provider_id,
            enabled=enabled_by_id.get(provider_id, default_search_provider_enabled(provider_id, value)),
            priority=index,
        )
        for index, provider_id in enumerate(ordered)
    ]
    return value.model_copy(
        update={
            "search_providers": normalized,
            "enable_open_facts": any(provider.enabled for provider in normalized if provider.id.startswith("open_")),
            "enable_upcitemdb": any(provider.enabled for provider in normalized if provider.id == "upcitemdb"),
            "enable_web_search": any(provider.enabled for provider in normalized if provider.id == "web_search"),
            "enable_llm_fallback": any(provider.enabled for provider in normalized if provider.id == "llm_fallback"),
        }
    )


def default_search_provider_enabled(provider_id: str, value: LookupSettings) -> bool:
    if provider_id.startswith("open_"):
        return value.enable_open_facts
    if provider_id == "upcitemdb":
        return value.enable_upcitemdb
    if provider_id == "web_search":
        return value.enable_web_search
    if provider_id == "llm_fallback":
        return value.enable_llm_fallback
    return True


class AppSettingsStore:
    def __init__(
        self,
        path: str,
        *,
        community_catalog_defaults: CommunityCatalogSettings | None = None,
        lookup_defaults: LookupSettings | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.community_catalog_defaults = community_catalog_defaults or default_community_catalog_settings()
        self.lookup_defaults = lookup_defaults or default_lookup_settings()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_community_catalog(self) -> CommunityCatalogSettings:
        payload = self._get_json("community_catalog")
        if payload is None:
            return self.community_catalog_defaults
        merged = self.community_catalog_defaults.model_dump()
        merged.update(payload)
        return CommunityCatalogSettings.model_validate(merged)

    def set_community_catalog(self, value: CommunityCatalogSettings) -> CommunityCatalogSettings:
        self._set_json("community_catalog", value.model_dump(mode="json"))
        return self.get_community_catalog()

    def update_community_catalog(self, value: CommunityCatalogSettingsUpdate) -> CommunityCatalogSettings:
        current = self.get_community_catalog()
        github_pat = value.github_pat.strip() if value.github_pat else current.github_pat
        updated = current.model_copy(
            update={
                "enabled": value.enabled,
                "repository_url": value.repository_url.strip() if value.repository_url else None,
                "github_pat": github_pat,
                "branch": value.branch.strip() or "main",
                "git_branch": value.branch.strip() or "main",
                "export_images": value.export_images,
                "auto_commit": value.auto_push,
                "auto_push": value.auto_push,
                "auto_push_ai_results": value.auto_push_ai_results,
                "auto_push_modified_products": value.auto_push_modified_products,
                "auto_push_manual_items": value.auto_push_manual_items,
                "author_name": value.author_name.strip() if value.author_name else DEFAULT_CATALOG_AUTHOR_NAME,
                "author_email": value.author_email.strip() if value.author_email else DEFAULT_CATALOG_AUTHOR_EMAIL,
                "path": current.workdir,
            }
        )
        return self.set_community_catalog(updated)

    def get_lookup(self) -> LookupSettings:
        payload = self._get_json("lookup")
        if payload is None:
            return normalize_lookup_settings(self.lookup_defaults)
        merged = self.lookup_defaults.model_dump()
        merged.update(payload)
        return normalize_lookup_settings(LookupSettings.model_validate(merged))

    def set_lookup(self, value: LookupSettings) -> LookupSettings:
        self._set_json("lookup", value.model_dump(mode="json"))
        return self.get_lookup()

    def update_lookup(self, value: LookupSettingsUpdate) -> LookupSettings:
        current = self.get_lookup()
        llm_api_key = value.llm_api_key.strip() if value.llm_api_key else current.llm_api_key
        provider = value.web_search_provider.strip().lower() or "duckduckgo"
        if provider not in {"duckduckgo", "searxng"}:
            provider = "duckduckgo"
        updated = current.model_copy(
            update={
                "enable_open_facts": value.enable_open_facts,
                "enable_upcitemdb": value.enable_upcitemdb,
                "enable_web_search": value.enable_web_search,
                "auto_request_missing_images": value.auto_request_missing_images,
                "search_providers": normalize_lookup_settings(LookupSettings.model_validate(value.model_dump())).search_providers,
                "web_search_provider": provider,
                "searxng_base_url": value.searxng_base_url.strip() if value.searxng_base_url else None,
                "enable_llm_fallback": value.enable_llm_fallback,
                "llm_base_url": value.llm_base_url.strip() or "https://api.openai.com/v1",
                "llm_api_key": llm_api_key,
                "llm_model": value.llm_model.strip() if value.llm_model else None,
            }
        )
        return self.set_lookup(updated)

    def community_catalog_status(self) -> CommunityCatalogStatus:
        current = self.get_community_catalog()
        path = Path(current.workdir if current.repository_url else current.path)
        return CommunityCatalogStatus(
            path=str(path),
            repository_url=current.repository_url,
            branch=current.branch or current.git_branch,
            path_exists=path.exists(),
            is_git_repo=(path / ".git").exists(),
            pending_changes=self._community_catalog_has_pending_changes(path),
            configured=bool(current.repository_url),
        )

    @staticmethod
    def _community_catalog_has_pending_changes(path: Path) -> bool:
        if not (path / ".git").exists():
            return False
        import subprocess

        try:
            result = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return False
        return bool(result.stdout.strip())

    def get_community_catalog_sources(self) -> CommunityCatalogSourceList:
        payload = self._get_json("community_catalog_sources")
        if payload is None:
            return CommunityCatalogSourceList()
        return CommunityCatalogSourceList.model_validate(payload)

    def set_community_catalog_sources(self, value: CommunityCatalogSourceList) -> CommunityCatalogSourceList:
        normalized: list[CommunityCatalogSource] = []
        seen: set[str] = set()
        for index, source in enumerate(value.sources):
            repository_url = source.repository_url.strip()
            if not repository_url:
                continue
            dedupe_key = repository_url.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(
                CommunityCatalogSource(
                    id=source.id or uuid4().hex,
                    name=source.name.strip() if source.name else None,
                    repository_url=repository_url,
                    enabled=source.enabled,
                    priority=index,
                    owner=source.owner,
                    description=source.description,
                    product_count=source.product_count,
                    validation_status=source.validation_status,
                    validation_message=source.validation_message,
                    warnings=list(source.warnings),
                    last_checked=source.last_checked,
                    last_successful_check=source.last_successful_check,
                    last_failed_check=source.last_failed_check,
                    last_error=source.last_error,
                )
            )
        saved = CommunityCatalogSourceList(sources=normalized)
        self._set_json("community_catalog_sources", saved.model_dump(mode="json"))
        return self.get_community_catalog_sources()

    def _get_json(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def _set_json(self, key: str, value: dict) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value, sort_keys=True)),
            )
