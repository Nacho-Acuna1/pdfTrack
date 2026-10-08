import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from App.api.dependencies import get_extraction_runtime
from App.api.request_parsing import read_pdf_upload, validate_pdf_signature
from App.core.config import settings
from App.domain.exceptions import (
    ExtractionOverloadedError,
    ExtractionTimedOutError,
    InvalidPdfError,
)
from App.domain.models import ExtractionResponse
from App.infrastructure.extraction_runtime import ExtractionRuntime


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Extraction"])


@router.post(
    "/extract",
    response_model=ExtractionResponse,
    status_code=status.HTTP_200_OK,
    response_model_exclude_none=True,
)
async def extract_pdf(
    request: Request,
    runtime: ExtractionRuntime = Depends(get_extraction_runtime),
) -> ExtractionResponse:
    try:
        await runtime.acquire()
    except ExtractionOverloadedError as exc:
        logger.warning(
            "extraction_rejected",
            extra={"reason": str(exc), "in_flight": runtime.in_flight},
        )
        raise HTTPException(
            status_code=settings.OVERLOAD_STATUS_CODE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc

    submitted = False
    try:
        upload = await read_pdf_upload(request, settings.max_file_size_bytes)
        validate_pdf_signature(upload.content)
        submitted = True
        content, page_count = await runtime.extract_admitted(upload.content)
    except ExtractionTimedOutError as exc:
        logger.warning("extraction_timeout", extra={"filename": upload.filename})
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except InvalidPdfError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    finally:
        if not submitted:
            runtime.release_admission()

    return ExtractionResponse(content=content, page_count=page_count)
