import pytest
from fastapi import HTTPException
from App.services.pdf_service import PdfExtractionService

class FakeExtractor:
    async def extract_text(self, file_bytes: bytes):
        pass

class FakeRepository:
    def __init__(self, existing_checksum=None):
        self.existing_checksum = existing_checksum

    async def get_by_checksum(self, checksum: str):
        if checksum == self.existing_checksum:
            # ¡AQUÍ ESTÁ LA MAGIA! Agregamos el formato exacto que espera el nuevo servicio
            return {
                "filename": "apunte_viejo.pdf",
                "total_pages": 1,
                "pages": [{"page_number": 1, "text": "Hola UTN", "word_occurrences": 0}]
            }
        return None

    async def save(self, doc_data: dict):
        pass

@pytest.mark.asyncio
async def test_retornar_documento_cacheado():
    """Prueba que si el documento ya existe, se devuelve desde la base de datos (Caché)."""
    pdf_bytes = b"Hola UTN"
    import hashlib
    checksum_esperado = hashlib.sha256(pdf_bytes).hexdigest()
    
    # Preparamos el repositorio simulando que ese Checksum YA EXISTE
    repo = FakeRepository(existing_checksum=checksum_esperado)
    extractor = FakeExtractor()
    service = PdfExtractionService(extractor=extractor, repository=repo)
    
    # Llamamos al servicio con el mismo archivo
    response = await service.process_pdf("apunte_nuevo.pdf", pdf_bytes)
    
    # Verificamos que no haya fallado y que devuelva los datos en caché
  # Reemplaza esta línea:
        # assert response.filename == "apunte_viejo.pdf"
        
        # Por esta línea:
    assert response.filename == "apunte_nuevo.pdf"
    assert len(response.pages) == 1
    assert response.pages[0].text == "Hola UTN"