from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    # Configuración general de la API
    PROJECT_NAME: str = "PDFtrack API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Podés agregar aquí límites, por ejemplo, tamaño máximo de archivo
    MAX_FILE_SIZE_MB: int = 10 

    # Configuración de Pydantic para manejar variables de entorno
    model_config = ConfigDict(case_sensitive=True)

# Instanciamos para que sea un Singleton y se importe en toda la app
settings = Settings()