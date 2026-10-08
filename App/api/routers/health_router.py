from fastapi import APIRouter, Request, Response, status


router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request, response: Response) -> dict[str, object]:
    runtime = getattr(request.app.state, "extraction_runtime", None)
    ready = runtime is not None and runtime.accepting
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "capacity": runtime.capacity if runtime else 0,
        "in_flight": runtime.in_flight if runtime else 0,
    }
