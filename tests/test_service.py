import hashlib

import pytest

from App.services.pdf_service import PdfExtractionService


class FakeExtractor:
    async def extract_text(self, file_bytes: bytes):
        raise AssertionError("No debe extraer cuando existe una entrada en caché")


class FakeRepository:
    def __init__(self, existing_checksum=None):
        self.existing_checksum = existing_checksum

    async def get_by_checksum(self, checksum: str):
        if checksum == self.existing_checksum:
            return {
                "filename": "apunte_viejo.pdf",
                "total_pages": 1,
                "pages": [
                    {"page_number": 1, "text": "Hola UTN", "word_occurrences": 0}
                ],
            }
        return None

    async def save(self, doc_data: dict):
        raise AssertionError("No debe guardar una entrada que ya existe")


@pytest.mark.asyncio
async def test_retornar_documento_cacheado():
    pdf_bytes = b"%PDF-1.7 cached test"
    checksum_esperado = hashlib.sha256(pdf_bytes).hexdigest()
    service = PdfExtractionService(
        extractor=FakeExtractor(),
        repository=FakeRepository(existing_checksum=checksum_esperado),
    )

    response = await service.process_pdf("apunte_nuevo.pdf", pdf_bytes)

    assert response.filename == "apunte_nuevo.pdf"
    assert len(response.pages) == 1
    assert response.pages[0].text == "Hola UTN"
