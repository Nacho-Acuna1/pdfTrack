from fastapi import APIRouter, UploadFile, File, Form, Depends
from App.api.dependencies import get_pdf_service
from App.services.pdf_service import PdfExtractionService
from App.domain.models import PdfExtractionResponse

router = APIRouter(prefix="/v1", tags=["Extraction"])

@router.post("/extract-text", response_model=PdfExtractionResponse)
async def extract_text_from_pdf(
    file: UploadFile = File(...),
    search_term: str = Form(None), 
    service: PdfExtractionService = Depends(get_pdf_service)
):
    file_bytes = await file.read()
    return await service.process_pdf(file.filename, file_bytes, search_term)