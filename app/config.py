from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env")

    lookup_cache_path: str = Field(default="/data/lookup-cache.sqlite3", alias="LOOKUP_CACHE_PATH")
    local_products_path: str = Field(default="/data/local-products.sqlite3", alias="LOCAL_PRODUCTS_PATH")
    auto_created_products_path: str = Field(
        default="/data/auto-created-products.sqlite3",
        alias="AUTO_CREATED_PRODUCTS_PATH",
    )
    lookup_request_timeout_seconds: float = Field(default=12, alias="LOOKUP_REQUEST_TIMEOUT_SECONDS")
    lookup_user_agent: str = Field(default="GrocyUltimateLookup/0.1", alias="LOOKUP_USER_AGENT")
    cache_min_confidence: float = Field(
        default=0.7,
        validation_alias=AliasChoices("CACHE_MIN_CONFIDENCE", "AUTO_FILL_MIN_CONFIDENCE"),
    )
    enable_open_facts: bool = Field(default=True, alias="ENABLE_OPEN_FACTS")
    enable_upcitemdb: bool = Field(default=True, alias="ENABLE_UPCITEMDB")
    enable_web_search: bool = Field(default=True, alias="ENABLE_WEB_SEARCH")
    web_search_provider: str = Field(default="duckduckgo", alias="WEB_SEARCH_PROVIDER")
    searxng_base_url: str | None = Field(default=None, alias="SEARXNG_BASE_URL")
    web_search_max_queries: int = Field(default=3, alias="WEB_SEARCH_MAX_QUERIES")
    web_search_max_results: int = Field(default=5, alias="WEB_SEARCH_MAX_RESULTS")
    web_search_fetch_limit: int = Field(default=3, alias="WEB_SEARCH_FETCH_LIMIT")
    enable_llm_fallback: bool = Field(default=False, alias="ENABLE_LLM_FALLBACK")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_max_page_chars: int = Field(default=12000, alias="LLM_MAX_PAGE_CHARS")
    enable_agent_search: bool = Field(default=True, alias="ENABLE_AGENT_SEARCH")
    agent_search_path: str = Field(default="/data/agent-search.sqlite3", alias="AGENT_SEARCH_PATH")
    agent_search_auth_path: str = Field(default="/secrets/auth.json", alias="AGENT_SEARCH_AUTH_PATH")
    agent_search_model: str = Field(default="gpt-5.4-mini", alias="AGENT_SEARCH_MODEL")
    agent_search_timeout_seconds: int = Field(default=300, alias="AGENT_SEARCH_TIMEOUT_SECONDS")
    agent_search_trigger_confidence: float = Field(default=0.45, alias="AGENT_SEARCH_TRIGGER_CONFIDENCE")
    auto_create_min_confidence: float = Field(default=0.8, alias="AUTO_CREATE_MIN_CONFIDENCE")
    scan_events_path: str = Field(default="/data/scan-events.sqlite3", alias="SCAN_EVENTS_PATH")
    app_settings_path: str = Field(default="/data/app-settings.sqlite3", alias="APP_SETTINGS_PATH")
    uploaded_images_path: str = Field(default="/data/uploaded-images", alias="UPLOADED_IMAGES_PATH")
    uploaded_images_base_url: str = Field(
        default="http://localhost:9290/uploaded-images",
        alias="UPLOADED_IMAGES_BASE_URL",
    )
    gul_api_key: str | None = Field(default=None, alias="GUL_API_KEY")
    scanner_device_tokens: str = Field(default="", alias="SCANNER_DEVICE_TOKENS")
    scanner_device_offline_after_seconds: int = Field(default=120, alias="SCANNER_DEVICE_OFFLINE_AFTER_SECONDS")
    community_catalog_enabled: bool = Field(default=False, alias="COMMUNITY_CATALOG_ENABLED")
    community_catalog_path: str = Field(default="/data/community-catalog", alias="COMMUNITY_CATALOG_PATH")
    community_catalog_queue_path: str = Field(
        default="/data/community-catalog-queue.sqlite3",
        alias="COMMUNITY_CATALOG_QUEUE_PATH",
    )
    community_catalog_workdir: str = Field(
        default="/data/community-catalog-workdir",
        alias="COMMUNITY_CATALOG_WORKDIR",
    )
    community_catalog_repository_url: str | None = Field(default=None, alias="COMMUNITY_CATALOG_REPOSITORY_URL")
    community_catalog_github_pat: str | None = Field(default=None, alias="COMMUNITY_CATALOG_GITHUB_PAT")
    community_catalog_export_images: bool = Field(default=True, alias="COMMUNITY_CATALOG_EXPORT_IMAGES")
    community_catalog_auto_commit: bool = Field(default=False, alias="COMMUNITY_CATALOG_AUTO_COMMIT")
    community_catalog_auto_push: bool = Field(default=True, alias="COMMUNITY_CATALOG_AUTO_PUSH")
    community_catalog_git_remote: str = Field(default="origin", alias="COMMUNITY_CATALOG_GIT_REMOTE")
    community_catalog_git_branch: str = Field(default="main", alias="COMMUNITY_CATALOG_GIT_BRANCH")
    community_catalog_author_name: str | None = Field(default=None, alias="COMMUNITY_CATALOG_AUTHOR_NAME")
    community_catalog_author_email: str | None = Field(default=None, alias="COMMUNITY_CATALOG_AUTHOR_EMAIL")
    grocy_url: str = Field(default="http://host.docker.internal:9283/api", alias="GROCY_URL")
    grocy_public_url: str = Field(default="http://localhost:9283", alias="GROCY_PUBLIC_URL")
    grocy_api_key: str | None = Field(default=None, alias="GROCY_API_KEY")


settings = Settings()
