import fitz  # PyMuPDF
from App.domain.models import ExtractedPage
from App.domain.interfaces import IPdfExtractor

class PyMuPdfExtractor(IPdfExtractor):
    async def extract_text(self, file_bytes: bytes) -> list[ExtractedPage]:
        pages = []
        try:
            # Abrimos el PDF desde los bytes en memoria
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Extraemos texto y eliminamos espacios extra o saltos de línea basura
                raw_text = page.get_text("text")
                clean_text = " ".join(raw_text.split()) 
                
                pages.append(
                    ExtractedPage(
                        page_number=page_num + 1,
                        text=clean_text
                    )
                )
            doc.close()
            return pages
        except Exception as e:
            raise ValueError(f"Error al procesar el PDF con PyMuPDF: {str(e)}")