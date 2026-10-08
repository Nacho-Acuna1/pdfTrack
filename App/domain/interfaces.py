from typing import Optional, Protocol

from App.domain.models import ExtractedPage


class IPdfExtractor(Protocol):
    async def extract_text(self, file_bytes: bytes) -> list[ExtractedPage]:
        ...


class IDocumentRepository(Protocol):
    async def save(self, document_data: dict) -> None:
        ...

    async def get_by_checksum(self, checksum: str) -> Optional[dict]:
        ...

    async def list_all(self) -> list[dict]:
        ...

    async def get_by_id(self, doc_id: str) -> Optional[dict]:
        ...

    async def update(self, doc_id: str, update_data: dict) -> Optional[dict]:
        ...

    async def delete(self, doc_id: str) -> bool:
        ...
