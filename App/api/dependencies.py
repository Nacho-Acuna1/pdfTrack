from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient

from App.core.config import settings
from App.infrastructure.extraction_runtime import ExtractionRuntime
from App.infrastructure.mongo_repository import MongoDocumentRepository
from App.infrastructure.null_repository import NullDocumentRepository
from App.infrastructure.pymupdf_extractor import PyMuPdfExtractor
from App.services.pdf_service import PdfExtractionService


_mongo_client: AsyncIOMotorClient | None = None


def get_extraction_runtime(request: Request) -> ExtractionRuntime:
    return request.app.state.extraction_runtime


def _get_repository():
    global _mongo_client
    if not settings.MONGODB_ENABLED:
        return NullDocumentRepository()

    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS,
        )
    return MongoDocumentRepository(_mongo_client[settings.DATABASE_NAME])


def get_pdf_service():
    return PdfExtractionService(
        extractor=PyMuPdfExtractor(),
        repository=_get_repository(),
    )


def close_mongo_client() -> None:
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None
