from motor.motor_asyncio import AsyncIOMotorClient
from App.core.config import settings
from App.infrastructure.pymupdf_extractor import PyMuPdfExtractor
from App.infrastructure.mongo_repository import MongoDocumentRepository
from App.services.pdf_service import PdfExtractionService

# 1. Conexión global a Mongo
client = AsyncIOMotorClient(settings.MONGODB_URL)
db = client[settings.DATABASE_NAME]

def get_pdf_service():
    # 2. Aquí es donde pasamos el 'db' que tu código de Mongo espera como 'db_client'
    repository = MongoDocumentRepository(db) 
    extractor = PyMuPdfExtractor()
    
    return PdfExtractionService(extractor=extractor, repository=repository)