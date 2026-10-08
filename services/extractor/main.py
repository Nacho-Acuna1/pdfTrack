import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.formparsers import MultiPartParser

from App.api.routers import health_router, public_extract_router
from App.core.config import settings
from App.core.logging import configure_logging
from App.infrastructure.extraction_runtime import ExtractionRuntime


SERVICE_NAME = "pdftrack-extractor"

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own only the CPU runtime required by this microservice."""

    MultiPartParser.spool_max_size = settings.max_file_size_bytes + 1
    runtime = ExtractionRuntime(
        workers=settings.EXTRACTION_WORKERS,
        queue_size=settings.EXTRACTION_QUEUE_SIZE,
        queue_wait_timeout=settings.QUEUE_WAIT_TIMEOUT_SECONDS,
        extraction_timeout=settings.EXTRACTION_TIMEOUT_SECONDS,
    )
    app.state.extraction_runtime = runtime
    logger.info(
        "service_started",
        extra={
            "service": SERVICE_NAME,
            "extraction_workers": runtime.workers,
            "queue_size": runtime.queue_size,
            "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
        },
    )
    try:
        yield
    finally:
        await runtime.close()
        logger.info("service_stopped", extra={"service": SERVICE_NAME})


app = FastAPI(
    title="PDFtrack Extractor API",
    description="Microservicio público de extracción de PDF a Markdown",
    version="3.0.0",
    lifespan=lifespan,
)

app.include_router(public_extract_router.router)
app.include_router(health_router.router)


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


@app.get("/")
async def root():
    return {
        "service": SERVICE_NAME,
        "status": "running",
        "extract_endpoint": "/extract",
        "docs": "/docs",
    }
