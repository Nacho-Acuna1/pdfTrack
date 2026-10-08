from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from starlette.datastructures import UploadFile


_BINARY_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


@dataclass(frozen=True)
class PdfUpload:
    filename: str
    content: bytes


async def read_pdf_upload(request: Request, max_bytes: int) -> PdfUpload:
    """Read multipart or binary input once, enforcing the limit while streaming."""

    media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()

    if media_type == "multipart/form-data":
        return await _read_multipart(request, max_bytes)
    if media_type in _BINARY_CONTENT_TYPES:
        return PdfUpload(
            filename=request.headers.get("x-filename", "document.pdf"),
            content=await _read_binary(request, max_bytes),
        )

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "Content-Type no soportado. Use multipart/form-data con el campo "
            "'file' o application/pdf."
        ),
    )


async def _read_multipart(request: Request, max_bytes: int) -> PdfUpload:
    try:
        async with request.form(max_files=1, max_fields=4) as form:
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Falta el archivo PDF en el campo 'file'.",
                )

            content_type = (upload.content_type or "").split(";", 1)[0].lower()
            filename = upload.filename or "document.pdf"
            if content_type not in _BINARY_CONTENT_TYPES or not filename.lower().endswith(
                ".pdf"
            ):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="El archivo debe tener extensión .pdf y tipo application/pdf.",
                )

            if upload.size is not None and upload.size > max_bytes:
                _raise_too_large(max_bytes)
            content = await upload.read(max_bytes + 1)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo interpretar el formulario multipart.",
        ) from exc

    _validate_size(content, max_bytes)
    return PdfUpload(filename=filename, content=content)


async def _read_binary(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                _raise_too_large(max_bytes)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length inválido.",
            )

    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > max_bytes:
            _raise_too_large(max_bytes)
    content = bytes(payload)
    _validate_size(content, max_bytes)
    return content


def validate_pdf_signature(content: bytes) -> None:
    if b"%PDF-" not in content[:1024]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El archivo no es un PDF válido o está corrupto.",
        )


def _validate_size(content: bytes, max_bytes: int) -> None:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )
    if len(content) > max_bytes:
        _raise_too_large(max_bytes)


def _raise_too_large(max_bytes: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"El archivo supera el máximo permitido de {max_bytes // (1024 * 1024)} MB.",
    )
