from pydantic import BaseModel
from typing import List, Optional

class ExtractedPage(BaseModel):
    page_number: int
    text: str
    word_occurrences: int = 0

class PdfExtractionResponse(BaseModel):
    filename: str
    total_pages: int
    pages: List[ExtractedPage]
    total_occurrences: int = 0
    search_term: Optional[str] = None