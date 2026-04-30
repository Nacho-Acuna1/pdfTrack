import pytest
from fastapi.testclient import TestClient
from App.main import app
from App.api.dependencies import get_pdf_service

client = TestClient(app)

# --- 1. CREAMOS UN ENTORNO FALSO (MOCK) ---
class FakeRepository:
    async def list_all(self):
        return [{"id": "doc_123", "filename": "apunte.pdf", "total_pages": 1}]
        
    async def get_by_id(self, doc_id: str):
        if doc_id == "doc_123":
            return {"id": "doc_123", "filename": "apunte.pdf"}
        return None # Simula el 404
        
    async def update(self, doc_id: str, data: dict):
        if doc_id == "doc_123":
            return {"id": "doc_123", "filename": data.get("filename", "apunte.pdf")}
        return None
        
    async def delete(self, doc_id: str):
        return doc_id == "doc_123"

class FakeService:
    def __init__(self):
        self.repository = FakeRepository()

# --- 2. SOBRESCRIBIMOS LA DEPENDENCIA ---
# Le decimos a FastAPI: "Cuando alguien pida get_pdf_service, dale nuestro FakeService"
app.dependency_overrides[get_pdf_service] = lambda: FakeService()


# --- 3. LOS TESTS ---
def test_list_documents():
    """Prueba que el endpoint GET / devuelve la lista de documentos."""
    response = client.get("/api/v1/documents/")
    assert response.status_code == 200

def test_get_document_by_id_success():
    """Prueba que buscar un ID existente devuelve el documento."""
    response = client.get("/api/v1/documents/doc_123")
    assert response.status_code == 200

def test_get_document_by_id_not_found():
    """Prueba que buscar un ID que no existe devuelve error 404."""
    response = client.get("/api/v1/documents/doc_999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Documento no encontrado"

def test_update_document():
    """Prueba que se puede actualizar el nombre del archivo."""
    response = client.patch("/api/v1/documents/doc_123?new_filename=apunte_modificado.pdf")
    assert response.status_code == 200

def test_delete_document():
    """Prueba que se puede borrar un documento existente."""
    response = client.delete("/api/v1/documents/doc_123")
    assert response.status_code == 200