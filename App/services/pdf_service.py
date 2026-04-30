import hashlib
import re
from fastapi import HTTPException
from App.domain.interfaces import IPdfExtractor, IDocumentRepository
from App.domain.models import PdfExtractionResponse
from App.core.config import settings

class PdfExtractionService:
    def __init__(self, extractor: IPdfExtractor, repository: IDocumentRepository):
        self.extractor = extractor
        self.repository = repository

    async def process_pdf(self, filename: str, file_bytes: bytes, search_term: str = None) -> PdfExtractionResponse:
        # 1. Validaciones básicas
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF válido.")
        
        if len(file_bytes) > (settings.MAX_FILE_SIZE_MB * 1024 * 1024):
            raise HTTPException(status_code=413, detail="El archivo es demasiado grande.")

        # 2. Checksum y Caché (Base de datos)
        checksum = hashlib.sha256(file_bytes).hexdigest()
        existing_doc = await self.repository.get_by_checksum(checksum)

        if existing_doc:
            # Si ya existe en MongoDB, recuperamos las páginas cacheadas
            pages_data = existing_doc["pages"]
        else:
            # Si no existe, extraemos y guardamos
            try:
                extracted_pages = await self.extractor.extract_text(file_bytes)
                pages_data = [page.model_dump() for page in extracted_pages]
                
                await self.repository.save({
                    "filename": filename,
                    "checksum": checksum,
                    "total_pages": len(pages_data),
                    "pages": pages_data
                })
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # 3. Lógica del Buscador
        response_pages = []
        total_occurrences = 0

        for page_dict in pages_data:
            text = page_dict["text"]
            occurrences = 0
            
            # Contamos cuántas veces aparece usando Regex ignorando mayúsculas/minúsculas
            if search_term:
                matches = re.findall(re.escape(search_term), text, re.IGNORECASE)
                occurrences = len(matches)
                total_occurrences += occurrences

            response_pages.append({
                "page_number": page_dict["page_number"],
                "text": text,
                "word_occurrences": occurrences
            })

        return PdfExtractionResponse(
            filename=filename,
            total_pages=len(response_pages),
            pages=response_pages,
            total_occurrences=total_occurrences,
            search_term=search_term
        )