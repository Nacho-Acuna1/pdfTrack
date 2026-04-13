from fastapi import HTTPException
from App.domain.interfaces import IPdfExtractor
from App.domain.models import PdfExtractionResponse

class PdfExtractionService:
    def __init__(self, extractor: IPdfExtractor):
        self.extractor = extractor

    def process_pdf(self, filename: str, file_bytes: bytes) -> PdfExtractionResponse:
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF válido.")
        
        try:
            pages = self.extractor.extract_text(file_bytes)
            return PdfExtractionResponse(
                filename=filename,
                total_pages=len(pages),
                pages=pages
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error procesando PDF: {str(e)}")