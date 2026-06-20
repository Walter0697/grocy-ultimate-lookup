import json
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from app.config import settings


class LlmProductExtraction(BaseModel):
    found: bool
    name: str | None = None
    brand: str | None = None
    quantity: str | None = None
    size: str | None = None
    count: int | None = Field(default=None, ge=1)
    variant: str | None = None
    image_url: HttpUrl | None = None
    barcode_seen: bool = False


class LlmProvider(ABC):
    @abstractmethod
    async def extract_product(self, barcode: str, page_url: str, page_text: str) -> LlmProductExtraction | None:
        raise NotImplementedError


class OpenAiCompatibleLlmProvider(LlmProvider):
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model if model is not None else settings.llm_model

    async def extract_product(self, barcode: str, page_url: str, page_text: str) -> LlmProductExtraction | None:
        if not self.api_key or not self.model:
            return None

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract product information from retailer page text. "
                        "Return only JSON with keys: found, name, brand, quantity, size, count, variant, "
                        "image_url, barcode_seen. Set found=false when the page is not clearly a product page. "
                        "Never invent missing values. barcode_seen is true only when the exact barcode appears."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Barcode: {barcode}\nPage URL: {page_url}\nPage text:\n{page_text}",
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": settings.lookup_user_agent,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.lookup_request_timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            extracted = LlmProductExtraction.model_validate(json.loads(content))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError):
            return None

        if not extracted.found or not extracted.name:
            return None
        return extracted


def create_llm_provider(
    *,
    enabled: bool | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> LlmProvider | None:
    effective_enabled = settings.enable_llm_fallback if enabled is None else enabled
    effective_api_key = settings.llm_api_key if api_key is None else api_key
    effective_model = settings.llm_model if model is None else model
    if not effective_enabled or not effective_api_key or not effective_model:
        return None
    return OpenAiCompatibleLlmProvider(
        base_url=base_url or settings.llm_base_url,
        api_key=effective_api_key,
        model=effective_model,
    )
