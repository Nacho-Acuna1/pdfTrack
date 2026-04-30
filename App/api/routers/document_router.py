from fastapi import APIRouter, Depends, HTTPException
from App.api.dependencies import get_pdf_service
from App.services.pdf_service import PdfExtractionService

# Este prefix se suma al "/api" de main.py, formando "/api/v1/documents"
router = APIRouter(prefix="/v1/documents", tags=["Documents CRUD"])

@router.get("/")
async def list_documents(service: PdfExtractionService = Depends(get_pdf_service)):
    """Devuelve la lista de todos los documentos guardados."""
    # Accedemos a la base de datos a través del repositorio inyectado en el servicio
    documents = await service.repository.list_all()
    return documents

@router.get("/{document_id}")
async def get_document_by_id(document_id: str, service: PdfExtractionService = Depends(get_pdf_service)):
    """Busca un documento específico por su ID."""
    doc = await service.repository.get_by_id(document_id)
    
    # Esta es la validación exacta que busca el test: test_get_document_by_id_not_found
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    return doc

@router.patch("/{document_id}")
async def update_document(document_id: str, new_filename: str, service: PdfExtractionService = Depends(get_pdf_service)):
    """Actualiza el nombre de un archivo existente."""
    # Verificamos si existe primero
    existing_doc = await service.repository.get_by_id(document_id)
    if not existing_doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    # Actualizamos el documento
    updated_doc = await service.repository.update(document_id, {"filename": new_filename})
    return updated_doc

@router.delete("/{document_id}")
async def delete_document(document_id: str, service: PdfExtractionService = Depends(get_pdf_service)):
    """Borra un documento de la base de datos."""
    success = await service.repository.delete(document_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
        
    return {"message": "Documento eliminado correctamente"}