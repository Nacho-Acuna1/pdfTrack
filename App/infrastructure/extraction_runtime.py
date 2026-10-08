import asyncio
from concurrent.futures import Executor, ProcessPoolExecutor
from functools import partial
from typing import Callable

from App.domain.exceptions import (
    ExtractionOverloadedError,
    ExtractionTimedOutError,
)
from App.infrastructure.pymupdf_extractor import extract_pdf_to_markdown


ExtractionFunction = Callable[[bytes], tuple[str, int]]


class ExtractionRuntime:
    """Bounded process pool that isolates CPU work from the ASGI event loop."""

    def __init__(
        self,
        workers: int,
        queue_size: int,
        queue_wait_timeout: float,
        extraction_timeout: float,
        *,
        executor: Executor | None = None,
        extraction_function: ExtractionFunction = extract_pdf_to_markdown,
    ) -> None:
        self.workers = workers
        self.queue_size = queue_size
        self.capacity = workers + queue_size
        self.queue_wait_timeout = queue_wait_timeout
        self.extraction_timeout = extraction_timeout
        self._executor = executor or ProcessPoolExecutor(max_workers=workers)
        self._owns_executor = executor is None
        self._extract = extraction_function
        self._slots = asyncio.Semaphore(self.capacity)
        self._accepting = True
        self._in_flight = 0

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def extract(self, file_bytes: bytes) -> tuple[str, int]:
        await self.acquire()
        return await self.extract_admitted(file_bytes)

    async def acquire(self) -> None:
        if not self._accepting:
            raise ExtractionOverloadedError("El procesador se está deteniendo.")

        await self._acquire_slot()
        self._in_flight += 1

    async def extract_admitted(self, file_bytes: bytes) -> tuple[str, int]:
        """Submit bytes after the caller has reserved a capacity slot."""

        release_on_completion = False
        future = None

        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self._executor,
                partial(self._extract, file_bytes),
            )
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.extraction_timeout
            )
        except TimeoutError as exc:
            release_on_completion = True
            future.add_done_callback(lambda _: self._release_slot())
            raise ExtractionTimedOutError(
                "La extracción excedió el tiempo máximo permitido."
            ) from exc
        except asyncio.CancelledError:
            if future is not None:
                release_on_completion = True
                future.add_done_callback(lambda _: self._release_slot())
            raise
        finally:
            if not release_on_completion:
                self._release_slot()

    def release_admission(self) -> None:
        """Release a reservation when validation fails before worker submission."""

        self._release_slot()

    async def _acquire_slot(self) -> None:
        if self.queue_wait_timeout == 0:
            if self._slots.locked():
                raise ExtractionOverloadedError(
                    "No hay capacidad de procesamiento disponible."
                )
            await self._slots.acquire()
            return

        try:
            await asyncio.wait_for(
                self._slots.acquire(), timeout=self.queue_wait_timeout
            )
        except TimeoutError as exc:
            raise ExtractionOverloadedError(
                "La cola de procesamiento está completa."
            ) from exc

    def _release_slot(self) -> None:
        self._in_flight -= 1
        self._slots.release()

    async def close(self) -> None:
        self._accepting = False
        if self._owns_executor:
            await asyncio.to_thread(
                self._executor.shutdown, wait=True, cancel_futures=True
            )
