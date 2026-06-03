from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env")

    lookup_cache_path: str = Field(default="/data/lookup-cache.sqlite3", alias="LOOKUP_CACHE_PATH")
    local_products_path: str = Field(default="/data/local-products.sqlite3", alias="LOCAL_PRODUCTS_PATH")
    lookup_request_timeout_seconds: float = Field(default=12, alias="LOOKUP_REQUEST_TIMEOUT_SECONDS")
    lookup_user_agent: str = Field(default="GrocyUltimateLookup/0.1", alias="LOOKUP_USER_AGENT")
    auto_fill_min_confidence: float = Field(default=0.7, alias="AUTO_FILL_MIN_CONFIDENCE")
    enable_open_facts: bool = Field(default=True, alias="ENABLE_OPEN_FACTS")
    enable_upcitemdb: bool = Field(default=True, alias="ENABLE_UPCITEMDB")
    enable_web_search: bool = Field(default=True, alias="ENABLE_WEB_SEARCH")
    web_search_max_results: int = Field(default=5, alias="WEB_SEARCH_MAX_RESULTS")
    web_search_fetch_limit: int = Field(default=3, alias="WEB_SEARCH_FETCH_LIMIT")


settings = Settings()
