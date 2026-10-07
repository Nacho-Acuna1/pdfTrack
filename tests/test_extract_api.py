from fastapi.testclient import TestClient

from App.api.dependencies import get_extraction_runtime
from App.core.config import settings
from App.domain.exceptions import ExtractionOverloadedError
from App.main import app


def test_extract_multipart_contract_page_count_and_markdown(two_page_pdf):
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("sample.pdf", two_page_pdf, "application/pdf")},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"content", "page_count"}
    assert body["page_count"] == 2
    assert isinstance(body["content"], str)
    assert "## Página 1" in body["content"]
    assert "Título de prueba" in body["content"]
    assert "## Página 2" in body["content"]


def test_extract_accepts_binary_pdf(two_page_pdf):
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            content=two_page_pdf,
            headers={"Content-Type": "application/pdf"},
        )

    assert response.status_code == 200
    assert response.json()["page_count"] == 2


def test_extract_rejects_invalid_media_type():
    with TestClient(app) as client:
        response = client.post(
            "/extract", content=b"not a pdf", headers={"Content-Type": "text/plain"}
        )

    assert response.status_code == 415


def test_extract_rejects_corrupt_pdf():
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("broken.pdf", b"%PDF-1.7 broken", "application/pdf")},
        )

    assert response.status_code == 422


def test_extract_rejects_empty_file():
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )

    assert response.status_code == 400


def test_extract_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    oversized = b"%PDF-1.7\n" + (b"0" * (1024 * 1024))
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("large.pdf", oversized, "application/pdf")},
        )

    assert response.status_code == 413


class AlwaysBusyRuntime:
    in_flight = 2

    async def acquire(self):
        raise ExtractionOverloadedError("La cola de procesamiento está completa.")


def test_extract_returns_controlled_backpressure(two_page_pdf):
    app.dependency_overrides[get_extraction_runtime] = lambda: AlwaysBusyRuntime()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/extract",
                files={"file": ("sample.pdf", two_page_pdf, "application/pdf")},
            )
    finally:
        app.dependency_overrides.pop(get_extraction_runtime, None)

    assert response.status_code == settings.OVERLOAD_STATUS_CODE
    assert response.headers["retry-after"] == "1"


def test_extract_does_not_require_mongodb(two_page_pdf, monkeypatch):
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)
    monkeypatch.setattr(settings, "MONGODB_URL", "mongodb://127.0.0.1:1")
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("sample.pdf", two_page_pdf, "application/pdf")},
        )

    assert response.status_code == 200


def test_health_checks():
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        ready = client.get("/health/ready")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
