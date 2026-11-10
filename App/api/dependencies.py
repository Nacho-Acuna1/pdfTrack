import asyncio
import logging
from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorClient

from App.core.config import settings
from App.infrastructure.extraction_runtime import ExtractionRuntime
from App.infrastructure.mongo_repository import MongoDocumentRepository
from App.infrastructure.null_repository import NullDocumentRepository
from App.infrastructure.pymupdf_extractor import PyMuPdfExtractor
from App.services.pdf_service import PdfExtractionService

logger = logging.getLogger(__name__)

_mongo_client: AsyncIOMotorClient | None = None
_mongo_lock: asyncio.Lock | None = None


def get_extraction_runtime(request: Request) -> ExtractionRuntime:
    return request.app.state.extraction_runtime


def _get_mongo_lock() -> asyncio.Lock:
    global _mongo_lock
    if _mongo_lock is None:
        _mongo_lock = asyncio.Lock()
    return _mongo_lock


async def get_mongo_client() -> AsyncIOMotorClient | None:
    """Returns the singleton AsyncIOMotorClient instance.

    Uses double-checked locking with asyncio.Lock to avoid race conditions
    when multiple concurrent requests initialize the client simultaneously,
    preventing duplicate connections and resource leaks without unnecessary locking.
    """
    global _mongo_client
    if not settings.MONGODB_ENABLED:
        return None

    # Fast path: already initialized (no lock needed)
    if _mongo_client is not None:
        return _mongo_client

    lock = _get_mongo_lock()
    async with lock:
        # Second check inside lock
        if _mongo_client is None:
            try:
                client = AsyncIOMotorClient(
                    settings.MONGODB_URL,
                    serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS,
                )
                _mongo_client = client
                logger.info(
                    "mongodb_client_initialized",
                    extra={"url": settings.MONGODB_URL, "database": settings.DATABASE_NAME},
                )
            except Exception as exc:
                logger.error(
                    "mongodb_client_initialization_error",
                    extra={"error": str(exc)},
                )
                raise

    return _mongo_client


async def ping_mongo(client: AsyncIOMotorClient | None = None) -> bool:
    """Pings MongoDB to verify that the cluster is reachable and responsive."""
    if not settings.MONGODB_ENABLED:
        return True

    try:
        if client is None:
            client = await get_mongo_client()
        if client is None:
            return False
        await client.admin.command("ping")
        return True
    except Exception as exc:
        logger.warning("mongodb_ping_failed", extra={"error": str(exc)})
        return False


async def get_repository():
    """Asynchronous dependency for the document repository."""
    if not settings.MONGODB_ENABLED:
        return NullDocumentRepository()

    client = await get_mongo_client()
    return MongoDocumentRepository(client[settings.DATABASE_NAME])


def _get_repository():
    """Synchronous fallback repository accessor for legacy or non-async callers."""
    global _mongo_client
    if not settings.MONGODB_ENABLED:
        return NullDocumentRepository()

    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS,
        )
    return MongoDocumentRepository(_mongo_client[settings.DATABASE_NAME])


async def get_pdf_service(repository=Depends(get_repository)) -> PdfExtractionService:
    """FastAPI dependency providing the PdfExtractionService."""
    if repository is None or not hasattr(repository, "get_by_checksum"):
        repository = await get_repository()
    return PdfExtractionService(
        extractor=PyMuPdfExtractor(),
        repository=repository,
    )


def close_mongo_client() -> None:
    """Gracefully closes the active MongoDB client and resets the singleton state."""
    global _mongo_client, _mongo_lock
    if _mongo_client is not None:
        try:
            _mongo_client.close()
            logger.info("mongodb_client_closed")
        except Exception as exc:
            logger.warning("mongodb_client_close_error", extra={"error": str(exc)})
        finally:
            _mongo_client = None
    _mongo_lock = None
