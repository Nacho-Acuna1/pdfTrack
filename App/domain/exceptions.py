class InvalidPdfError(ValueError):
    """Raised when PyMuPDF cannot open or process the supplied payload."""


class ExtractionOverloadedError(RuntimeError):
    """Raised when all worker and bounded queue slots are occupied."""


class ExtractionTimedOutError(TimeoutError):
    """Raised when extraction exceeds the configured response deadline."""
