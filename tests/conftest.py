import pymupdf
import pytest


@pytest.fixture(scope="session")
def two_page_pdf() -> bytes:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 72), "Título de prueba", fontsize=18)
    first.insert_text((72, 110), "Primer párrafo extraído.", fontsize=11)
    second = document.new_page()
    second.insert_text((72, 72), "Segunda página", fontsize=16)
    second.insert_text((72, 110), "Contenido final.", fontsize=11)
    payload = document.tobytes()
    document.close()
    return payload
