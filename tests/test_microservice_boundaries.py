from fastapi.testclient import TestClient

from services.documents.main import app as documents_app
from services.extractor.main import app as extractor_app


def test_document_service_does_not_expose_public_extractor():
    with TestClient(documents_app) as client:
        response = client.post(
            "/extract",
            content=b"%PDF-1.7",
            headers={"Content-Type": "application/pdf"},
        )

    assert response.status_code == 404


def test_services_publish_distinct_openapi_contracts():
    with TestClient(extractor_app) as extractor_client:
        extractor_paths = extractor_client.get("/openapi.json").json()["paths"]
    with TestClient(documents_app) as documents_client:
        document_paths = documents_client.get("/api/openapi.json").json()["paths"]

    assert "/extract" in extractor_paths
    assert "/api/v1/documents/" not in extractor_paths
    assert "/api/v1/documents/" in document_paths
    assert "/extract" not in document_paths
