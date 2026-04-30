from fastapi import FastAPI
from App.api.routers import extract_router, document_router

app = FastAPI(
    title="PDFtrack API",
    description="API para extracción de texto de PDFs con Arquitectura Limpia",
    version="1.0.0"
)

# Conectamos AMBAS rutas a la aplicación principal
app.include_router(extract_router.router, prefix="/api")
app.include_router(document_router.router, prefix="/api")  # <-- ¡ESTA LÍNEA ES LA CLAVE PARA EL CRUD!

@app.get("/")
def root():
    return {"message": "PDFtrack API is running"}