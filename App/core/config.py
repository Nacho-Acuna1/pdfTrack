from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "PDFtrack"
    # Cambia localhost por mongodb si usas Docker, o déjalo así si corre local
    MONGODB_URL: str = "mongodb://localhost:27017" 
    DATABASE_NAME: str = "pdf_extraction_db"
    MAX_FILE_SIZE_MB: int = 10

    class Config:
        case_sensitive = True

settings = Settings()