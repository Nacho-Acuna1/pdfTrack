import hashlib
import logging
import re

from fastapi import HTTPException

from App.domain.interfaces import IPdfExtractor, IDocumentRepository
from App.domain.models import PdfExtractionResponse
from App.core.config import settings
from App.domain.exceptions import InvalidPdfError


logger = logging.getLogger(__name__)

class PdfExtractionService:
    def __init__(self, extractor: IPdfExtractor, repository: IDocumentRepository):
        self.extractor = extractor
        self.repository = repository

    async def process_pdf(self, filename: str, file_bytes: bytes, search_term: str = None) -> PdfExtractionResponse:
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF válido.")

        if not file_bytes:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")

        if len(file_bytes) > settings.max_file_size_bytes:
            raise HTTPException(status_code=413, detail="El archivo es demasiado grande.")

        if b"%PDF-" not in file_bytes[:1024]:
            raise HTTPException(status_code=422, detail="El archivo no es un PDF válido.")

        checksum = hashlib.sha256(file_bytes).hexdigest()
        try:
            existing_doc = await self.repository.get_by_checksum(checksum)
        except Exception:
            logger.warning("mongo_cache_read_failed", exc_info=True)
            existing_doc = None

        if existing_doc:
            pages_data = existing_doc["pages"]
        else:
            try:
                extracted_pages = await self.extractor.extract_text(file_bytes)
                pages_data = [page.model_dump() for page in extracted_pages]

            except InvalidPdfError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

            try:
                await self.repository.save({
                    "filename": filename,
                    "checksum": checksum,
                    "total_pages": len(pages_data),
                    "pages": pages_data
                })
            except Exception:
                logger.warning("mongo_cache_write_failed", exc_info=True)

        response_pages = []
        total_occurrences = 0

        for page_dict in pages_data:
            text = page_dict["text"]
            occurrences = 0
            
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
