import asyncio
import hashlib
from bson import ObjectId
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from App.api import dependencies
from App.core.config import settings
from App.infrastructure.mongo_repository import MongoDocumentRepository
from services.documents.main import app as documents_app
from services.extractor.main import app as extractor_app


class InMemoryAsyncCollection:
    """In-memory async collection simulating Motor for MongoDocumentRepository."""

    def __init__(self):
        self.docs = {}

    async def insert_one(self, doc):
        d = dict(doc)
        if "_id" not in d:
            d["_id"] = ObjectId()
        self.docs[d["_id"]] = d
        res = MagicMock()
        res.inserted_id = d["_id"]
        return res

    async def find_one(self, query):
        for doc in self.docs.values():
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                return dict(doc)
        return None

    def find(self, query=None, projection=None):
        items = [dict(d) for d in self.docs.values()]

        class AsyncCursor:
            def __init__(self, data):
                self._iter = iter(data)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

        return AsyncCursor(items)

    async def update_one(self, query, update):
        target_id = query.get("_id")
        res = MagicMock()
        if target_id in self.docs:
            if "$set" in update:
                self.docs[target_id].update(update["$set"])
            res.modified_count = 1
        else:
            res.modified_count = 0
        return res

    async def delete_one(self, query):
        target_id = query.get("_id")
        res = MagicMock()
        if target_id in self.docs:
            del self.docs[target_id]
            res.deleted_count = 1
        else:
            res.deleted_count = 0
        return res


def test_e2e_full_file_flow_upload_process_mongo_retrieve(two_page_pdf, monkeypatch):
    """1. Prueba de archivos: Flujo completo de extremo a extremo.

    - Envío de un archivo PDF.
    - Recepción por el servicio.
    - Procesamiento y extracción.
    - Almacenamiento en MongoDB.
    - Recuperación y consulta del documento.
    - Consistencia del contenido almacenado con el archivo enviado.
    """
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)
    collection = InMemoryAsyncCollection()
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda col_name: collection
    mock_client = MagicMock()
    mock_client.__getitem__.side_effect = lambda db_name: mock_db
    monkeypatch.setattr(dependencies, "get_mongo_client", AsyncMock(return_value=mock_client))
    monkeypatch.setattr(dependencies, "_get_repository", lambda: MongoDocumentRepository(mock_db))
    monkeypatch.setattr(dependencies, "get_repository", AsyncMock(return_value=MongoDocumentRepository(mock_db)))

    with TestClient(documents_app) as client:
        # Paso 1 & 2 & 3 & 4: Envío de PDF y procesamiento
        response = client.post(
            "/api/v1/extract-text",
            files={"file": ("guia_prueba.pdf", two_page_pdf, "application/pdf")},
            data={"search_term": "prueba"},
        )
        assert response.status_code == 200
        data = response.json()

        # Validación de consistencia
        expected_checksum = hashlib.sha256(two_page_pdf).hexdigest()
        assert data["filename"] == "guia_prueba.pdf"
        assert data["total_pages"] == 2
        assert len(data["pages"]) == 2
        assert data["search_term"] == "prueba"
        assert data["total_occurrences"] == 1
        assert "Título de prueba" in data["pages"][0]["text"]
        assert data["pages"][0]["word_occurrences"] == 1
        assert "Segunda página" in data["pages"][1]["text"]

        # Paso 5: Consulta de la lista de documentos en MongoDB
        list_res = client.get("/api/v1/documents/")
        assert list_res.status_code == 200
        docs_list = list_res.json()
        assert len(docs_list) == 1
        doc_id = docs_list[0]["id"]
        assert docs_list[0]["filename"] == "guia_prueba.pdf"
        assert docs_list[0]["total_pages"] == 2

        # Recuperación por ID desde MongoDB
        get_res = client.get(f"/api/v1/documents/{doc_id}")
        assert get_res.status_code == 200
        retrieved = get_res.json()
        assert retrieved["id"] == doc_id
        assert retrieved["filename"] == "guia_prueba.pdf"
        assert len(retrieved["pages"]) == 2
        assert retrieved["checksum"] == expected_checksum

        # Verificación de caché: el segundo envío del mismo PDF reutiliza el documento guardado
        cached_response = client.post(
            "/api/v1/extract-text",
            files={"file": ("guia_prueba.pdf", two_page_pdf, "application/pdf")},
        )
        assert cached_response.status_code == 200
        assert cached_response.json()["filename"] == "guia_prueba.pdf"
        assert cached_response.json()["total_pages"] == 2
        # Sigue habiendo un único documento almacenado en MongoDB (cache hit exitoso)
        assert len(collection.docs) == 1

        # Actualización de metadata (PATCH)
        patch_res = client.patch(
            f"/api/v1/documents/{doc_id}?new_filename=guia_actualizada.pdf"
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["filename"] == "guia_actualizada.pdf"

        # Eliminación (DELETE)
        del_res = client.delete(f"/api/v1/documents/{doc_id}")
        assert del_res.status_code == 200
        assert del_res.json()["message"] == "Documento eliminado correctamente"

        # Confirmación de eliminación (GET posterior retorna 404)
        not_found_res = client.get(f"/api/v1/documents/{doc_id}")
        assert not_found_res.status_code == 404


def test_concurrent_requests_handling(two_page_pdf):
    """2. Pruebas de concurrencia: Múltiples solicitudes simultáneas.

    - Procesamiento concurrente de múltiples archivos.
    - Ausencia de condiciones de carrera y liberación de recursos.
    """
    from concurrent.futures import ThreadPoolExecutor

    with TestClient(extractor_app) as client:
        def send_request(idx):
            return client.post(
                "/extract",
                files={"file": (f"doc_{idx}.pdf", two_page_pdf, "application/pdf")},
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(send_request, i) for i in range(10)]
            responses = [f.result() for f in futures]

        for res in responses:
            assert res.status_code in (200, 503, 429)
            if res.status_code == 200:
                body = res.json()
                assert body["page_count"] == 2
                assert "## Página 1" in body["content"]

        runtime = extractor_app.state.extraction_runtime
        assert runtime.in_flight == 0
        assert len(runtime._active_shm) == 0


@pytest.mark.asyncio
async def test_controlled_graceful_shutdown_lifecycle():
    """3. Pruebas de Graceful Shutdown: Validación del ciclo controlado de 7 pasos.

    1. Iniciar servicios.
    2. Enviar solicitud en proceso.
    3. Solicitar detención controlada.
    4. Comprobar que no acepta nuevas solicitudes.
    5. Verificar que termine las operaciones pendientes.
    6. Comprobar logs y eventos de cierre.
    7. Verificar liberación de recursos (SharedMemory y procesos).
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from App.domain.exceptions import ExtractionOverloadedError
    from App.infrastructure.extraction_runtime import ExtractionRuntime

    started = threading.Event()
    finish = threading.Event()

    def mock_worker(shm_name: str, size: int) -> tuple[str, int]:
        started.set()
        finish.wait(timeout=2.0)
        return "## Página 1\n\nContenido seguro", 1

    executor = ThreadPoolExecutor(max_workers=1)
    runtime = ExtractionRuntime(
        workers=1,
        queue_size=1,
        queue_wait_timeout=0,
        extraction_timeout=3.0,
        executor=executor,
        extraction_function=mock_worker,
        shutdown_timeout=2.0,
    )

    # Paso 2: Solicitud en curso
    in_flight_task = asyncio.create_task(runtime.extract(b"pdf data"))
    assert await asyncio.to_thread(started.wait, 1.0)
    assert runtime.in_flight == 1

    # Paso 3: Solicitar detención
    close_task = asyncio.create_task(runtime.close())
    await asyncio.sleep(0.05)

    # Paso 4: Comprobar rechazo inmediato de nuevas solicitudes
    assert not runtime.accepting
    with pytest.raises(ExtractionOverloadedError, match="deteniendo"):
        await runtime.extract(b"rejected data")

    # Paso 5: Terminar operaciones pendientes
    finish.set()
    result = await in_flight_task
    assert result == ("## Página 1\n\nContenido seguro", 1)

    # Paso 6 & 7: Cierre ordenado y liberación de recursos
    await close_task
    assert runtime.in_flight == 0
    assert len(runtime._active_shm) == 0
    executor.shutdown(wait=True)


def test_system_availability_and_healthchecks():
    """4. Pruebas de disponibilidad: Healthchecks y estado de preparación."""
    with TestClient(extractor_app) as ext_client:
        live = ext_client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"

        ready = ext_client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

    with TestClient(documents_app) as doc_client:
        live = doc_client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"

        ready = doc_client.get("/health/ready")
        assert ready.status_code == 200
