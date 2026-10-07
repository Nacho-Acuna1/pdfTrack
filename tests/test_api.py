import pytest
from fastapi.testclient import TestClient

from App.api.dependencies import get_pdf_service
from App.main import app


class FakeRepository:
    async def list_all(self):
        return [{"id": "doc_123", "filename": "apunte.pdf", "total_pages": 1}]

    async def get_by_id(self, doc_id: str):
        if doc_id == "doc_123":
            return {"id": "doc_123", "filename": "apunte.pdf"}
        return None

    async def update(self, doc_id: str, data: dict):
        if doc_id == "doc_123":
            return {"id": "doc_123", "filename": data["filename"]}
        return None

    async def delete(self, doc_id: str):
        return doc_id == "doc_123"


class FakeService:
    def __init__(self):
        self.repository = FakeRepository()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_pdf_service] = lambda: FakeService()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_pdf_service, None)


def test_list_documents(client):
    response = client.get("/api/v1/documents/")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "doc_123"


def test_get_document_by_id_success(client):
    response = client.get("/api/v1/documents/doc_123")
    assert response.status_code == 200


def test_get_document_by_id_not_found(client):
    response = client.get("/api/v1/documents/doc_999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Documento no encontrado"


def test_update_document(client):
    response = client.patch(
        "/api/v1/documents/doc_123?new_filename=apunte_modificado.pdf"
    )
    assert response.status_code == 200
    assert response.json()["filename"] == "apunte_modificado.pdf"


def test_delete_document(client):
    response = client.delete("/api/v1/documents/doc_123")
    assert response.status_code == 200
