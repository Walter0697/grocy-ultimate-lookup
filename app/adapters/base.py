from abc import ABC, abstractmethod

from app.models import LookupResult


class LookupAdapter(ABC):
    name: str

    @abstractmethod
    async def lookup(self, barcode: str) -> LookupResult | None:
        raise NotImplementedError
