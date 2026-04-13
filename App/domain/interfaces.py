from typing import Protocol, List
from App.domain.models import ExtractedPage

class IPdfExtractor(Protocol):
    def extract_text(self, file_bytes: bytes) -> List[ExtractedPage]:
        """Extrae el texto de un archivo PDF y devuelve una lista de páginas."""
        ...