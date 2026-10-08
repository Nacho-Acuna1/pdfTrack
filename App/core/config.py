from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Operational configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    PROJECT_NAME: str = "PDFtrack"
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)
    HTTP_WORKERS: int = Field(default=1, ge=1, le=4)
    LOG_LEVEL: str = "INFO"

    MAX_FILE_SIZE_MB: int = Field(default=10, ge=1, le=100)
    EXTRACTION_WORKERS: int = Field(default=1, ge=1, le=4)
    EXTRACTION_QUEUE_SIZE: int = Field(default=1, ge=0, le=100)
    QUEUE_WAIT_TIMEOUT_SECONDS: float = Field(default=0.0, ge=0.0, le=30.0)
    EXTRACTION_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0.0, le=300.0)
    OVERLOAD_STATUS_CODE: int = 503

    MONGODB_ENABLED: bool = False
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "pdf_extraction_db"
    MONGODB_TIMEOUT_MS: int = Field(default=500, ge=100, le=30_000)

    @field_validator("OVERLOAD_STATUS_CODE")
    @classmethod
    def validate_overload_status(cls, value: int) -> int:
        if value not in (429, 503):
            raise ValueError("OVERLOAD_STATUS_CODE debe ser 429 o 503")
        return value

    @field_validator("LOG_LEVEL")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL no es válido")
        return normalized

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


settings = Settings()
