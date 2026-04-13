from App.infrastructure.pymupdf_extractor import PyMuPdfExtractor
from App.services.pdf_service import PdfExtractionService

def get_pdf_service() -> PdfExtractionService:
    # Aquí es donde decides qué implementación de infraestructura usar
    extractor = PyMuPdfExtractor()
    return PdfExtractionService(extractor)