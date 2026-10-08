import logging
from fastapi import FastAPI
from App.core.logging import configure_logging

configure_logging("INFO")
logger = logging.getLogger(__name__)

app = FastAPI(title="audit Service")

@app.get("/health/ready")
async def readiness():
    return {"status": "ready", "service": "audit"}

@app.post("/api/audit/dummy")
async def dummy():
    return {"message": "dummy endpoint for audit"}
