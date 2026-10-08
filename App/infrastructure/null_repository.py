class NullDocumentRepository:
    """Stateless repository used when the optional MongoDB cache is disabled."""

    async def get_by_checksum(self, checksum: str) -> None:
        return None

    async def save(self, document_data: dict) -> None:
        return None

    async def list_all(self) -> list[dict]:
        return []

    async def get_by_id(self, doc_id: str) -> None:
        return None

    async def update(self, doc_id: str, update_data: dict) -> None:
        return None

    async def delete(self, doc_id: str) -> bool:
        return False
