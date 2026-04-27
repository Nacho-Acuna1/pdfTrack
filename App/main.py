from fastapi import FastAPI
from App.api.routers import extract_router
from App.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

# Esta es la línea clave que "conecta" los endpoints al servidor
app.include_router(extract_router.router, prefix="/api")

@app.get("/")
def read_root():
    return {"message": "PDFtrack API is running"}