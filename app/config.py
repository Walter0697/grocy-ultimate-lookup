from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env")

    lookup_cache_path: str = Field(default="/data/lookup-cache.sqlite3", alias="LOOKUP_CACHE_PATH")
    local_products_path: str = Field(default="/data/local-products.sqlite3", alias="LOCAL_PRODUCTS_PATH")
    lookup_request_timeout_seconds: float = Field(default=12, alias="LOOKUP_REQUEST_TIMEOUT_SECONDS")
    lookup_user_agent: str = Field(default="GrocyUltimateLookup/0.1", alias="LOOKUP_USER_AGENT")
    enable_open_facts: bool = Field(default=True, alias="ENABLE_OPEN_FACTS")
    enable_upcitemdb: bool = Field(default=True, alias="ENABLE_UPCITEMDB")


settings = Settings()
