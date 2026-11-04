"""Backward-compatible entry point for the extraction microservice.

New deployments should start ``services.extractor.main:app`` explicitly. The
alias keeps the original local command working without joining the document
routes and the CPU-intensive extraction runtime in the same process.
"""

import os
import uvicorn

from services.extractor.main import app

__all__ = ["app"]


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    workers = int(os.getenv("HTTP_WORKERS", "1"))
    uvicorn.run("App.main:app", host=host, port=port, workers=workers)
