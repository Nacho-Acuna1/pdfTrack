from fastapi import APIRouter, Depends, File, Form, UploadFile

from App.api.dependencies import get_pdf_service
from App.core.config import settings
from App.domain.models import PdfExtractionResponse
from App.services.pdf_service import PdfExtractionService

router = APIRouter(prefix="/v1", tags=["Extraction"])

@router.post("/extract-text", response_model=PdfExtractionResponse)
async def extract_text_from_pdf(
    file: UploadFile = File(...),
    search_term: str | None = Form(None),
    service: PdfExtractionService = Depends(get_pdf_service)
):
    file_bytes = await file.read(settings.max_file_size_bytes + 1)
    return await service.process_pdf(file.filename, file_bytes, search_term)
