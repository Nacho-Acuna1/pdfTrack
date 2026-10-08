"""Backward-compatible entry point for the extraction microservice.

New deployments should start ``services.extractor.main:app`` explicitly. The
alias keeps the original local command working without joining the document
routes and the CPU-intensive extraction runtime in the same process.
"""

from services.extractor.main import app


__all__ = ["app"]
