import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status

from App.api.dependencies import close_mongo_client, ping_mongo
from App.api.routers import document_router, extract_router
from App.core.config import settings
from App.core.logging import configure_logging


SERVICE_NAME = "pdftrack-documents"

configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.is_ready = True
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
        app.state.is_ready = False
        logger.info("service_stopping", extra={"service": SERVICE_NAME})
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
async def readiness(request: Request, response: Response) -> dict[str, object]:
    is_ready = getattr(request.app.state, "is_ready", True)
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "service": SERVICE_NAME,
            "reason": "shutting_down",
        }

    if not settings.MONGODB_ENABLED:
        return {
            "status": "ready",
            "service": SERVICE_NAME,
            "persistence": "stateless",
        }

    mongo_healthy = await ping_mongo()
    if not mongo_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "service": SERVICE_NAME,
            "persistence": "mongodb",
            "database": "disconnected",
        }

    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "persistence": "mongodb",
        "database": "connected",
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


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8001"))
    host = os.getenv("HOST", settings.HOST)
    workers = int(os.getenv("DOCUMENTS_HTTP_WORKERS", "1"))
    uvicorn.run(
        "services.documents.main:app",
        host=host,
        port=port,
        workers=workers,
        timeout_graceful_shutdown=settings.SHUTDOWN_TIMEOUT_SECONDS,
    )
