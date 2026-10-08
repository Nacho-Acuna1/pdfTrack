import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from App.api.dependencies import close_mongo_client
from App.api.routers import document_router, extract_router
from App.core.config import settings
from App.core.logging import configure_logging


SERVICE_NAME = "pdftrack-documents"

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "service_started",
        extra={
            "service": SERVICE_NAME,
            "mongodb_enabled": settings.MONGODB_ENABLED,
        },
    )
    try:
        yield
    finally:
        close_mongo_client()
        logger.info("service_stopped", extra={"service": SERVICE_NAME})


app = FastAPI(
    title="PDFtrack Documents API",
    description="Microservicio de compatibilidad, caché y CRUD documental",
    version="3.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(extract_router.router, prefix="/api")
app.include_router(document_router.router, prefix="/api")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "request_completed",
        extra={
            "service": SERVICE_NAME,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/health/ready")
async def readiness() -> dict[str, object]:
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "persistence": "mongodb" if settings.MONGODB_ENABLED else "stateless",
    }


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": SERVICE_NAME,
        "status": "running",
        "legacy_extract_endpoint": "/api/v1/extract-text",
        "documents_endpoint": "/api/v1/documents/",
        "docs": "/api/docs",
    }
