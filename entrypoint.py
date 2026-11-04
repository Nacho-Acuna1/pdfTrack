"""Container entrypoint implementing 12-Factor App Factor VII (Port Binding).

Runs the specified FastAPI/ASGI application using Uvicorn in user space,
binding directly to the port provided by the execution environment via the
PORT environment variable (defaulting to 8000). Avoids shell invocation (`sh -c`)
to prevent shell injection vulnerabilities and ensure direct OS signal propagation.
"""

import os
import uvicorn


def main() -> None:
    service_module = os.getenv("SERVICE_MODULE", "services.extractor.main:app")
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("HTTP_WORKERS", "1"))

    uvicorn.run(
        service_module,
        host=host,
        port=port,
        workers=workers,
        access_log=False,
    )


if __name__ == "__main__":
    main()
