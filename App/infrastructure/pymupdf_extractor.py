import asyncio
import pymupdf

from App.domain.exceptions import InvalidPdfError
from App.domain.models import ExtractedPage
from App.domain.interfaces import IPdfExtractor


def _page_markdown(page: pymupdf.Page, page_number: int) -> str:
    """Produce stable, lightweight Markdown without OCR or disk I/O."""

    heading = f"## Página {page_number}"
    text = " ".join(page.get_text("text").split())
    return f"{heading}\n\n{text}" if text else heading


def extract_pdf_to_markdown(file_bytes: bytes) -> tuple[str, int]:
    """CPU worker entry point; kept at module level so it is process-picklable."""

    try:
        with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
            page_count = document.page_count
            pages = [
                _page_markdown(document.load_page(index), index + 1)
                for index in range(page_count)
            ]
    except Exception as exc:
        raise InvalidPdfError("El archivo no es un PDF válido o está corrupto.") from exc

    return "\n\n---\n\n".join(pages), page_count


class PyMuPdfExtractor(IPdfExtractor):
    async def extract_text(self, file_bytes: bytes) -> list[ExtractedPage]:
        return await asyncio.to_thread(self._extract_sync, file_bytes)

    @staticmethod
    def _extract_sync(file_bytes: bytes) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        try:
            with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
                for page_num, page in enumerate(document, start=1):
                    raw_text = page.get_text("text")
                    clean_text = " ".join(raw_text.split())
                    pages.append(
                        ExtractedPage(page_number=page_num, text=clean_text)
                    )
            return pages
        except Exception as exc:
            raise InvalidPdfError(
                "El archivo no es un PDF válido o está corrupto."
            ) from exc
