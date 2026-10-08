import logging
from fastapi import FastAPI
from App.core.logging import configure_logging

configure_logging("INFO")
logger = logging.getLogger(__name__)

app = FastAPI(title="storage Service")

@app.get("/health/ready")
async def readiness():
    return {"status": "ready", "service": "storage"}

@app.post("/api/storage/dummy")
async def dummy():
    return {"message": "dummy endpoint for storage"}
