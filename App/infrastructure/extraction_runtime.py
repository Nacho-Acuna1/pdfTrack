import asyncio
from concurrent.futures import Executor, ProcessPoolExecutor
from functools import partial
import logging
from multiprocessing.shared_memory import SharedMemory
from typing import Callable

from App.domain.exceptions import (
    ExtractionOverloadedError,
    ExtractionTimedOutError,
)
from App.infrastructure.pymupdf_extractor import extract_pdf_to_markdown

ExtractionFunction = Callable[[str, int], tuple[str, int]]
logger = logging.getLogger(__name__)


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
        shutdown_timeout: float | None = None,
    ) -> None:
        self.workers = workers
        self.queue_size = queue_size
        self.capacity = workers + queue_size
        self.queue_wait_timeout = queue_wait_timeout
        self.extraction_timeout = extraction_timeout
        self.shutdown_timeout = (
            shutdown_timeout if shutdown_timeout is not None else extraction_timeout
        )
        self._executor = executor or ProcessPoolExecutor(max_workers=workers)
        self._owns_executor = executor is None
        self._extract = extraction_function
        self._slots = asyncio.Semaphore(self.capacity)
        self._accepting = True
        self._in_flight = 0
        self._drain_event = asyncio.Event()
        self._drain_event.set()
        self._active_shm: set[SharedMemory] = set()
        self._closed = False

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
        if not self._accepting or self._closed:
            raise ExtractionOverloadedError("El procesador se está deteniendo.")

        await self._acquire_slot()
        self._in_flight += 1
        self._drain_event.clear()

    async def extract_admitted(self, file_bytes: bytes) -> tuple[str, int]:
        """Submit bytes after the caller has reserved a capacity slot."""

        size = len(file_bytes)
        shm = SharedMemory(create=True, size=size)
        self._register_shm(shm)
        shm.buf[:size] = file_bytes

        def cleanup_shm_and_release(f=None):
            self._unregister_shm(shm)
            self._release_slot()
            try:
                shm.close()
            except Exception:
                pass
            try:
                shm.unlink()
            except Exception:
                pass

        release_on_completion = False
        future = None

        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self._executor,
                partial(self._extract, shm.name, size),
            )
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.extraction_timeout
            )
        except TimeoutError as exc:
            release_on_completion = True
            future.add_done_callback(cleanup_shm_and_release)
            raise ExtractionTimedOutError(
                "La extracción excedió el tiempo máximo permitido."
            ) from exc
        except asyncio.CancelledError:
            if future is not None:
                release_on_completion = True
                future.add_done_callback(cleanup_shm_and_release)
            raise
        finally:
            if not release_on_completion:
                cleanup_shm_and_release()

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
        if self._in_flight <= 0:
            self._in_flight = 0
            self._drain_event.set()
        self._slots.release()

    def _register_shm(self, shm: SharedMemory) -> None:
        self._active_shm.add(shm)

    def _unregister_shm(self, shm: SharedMemory) -> None:
        self._active_shm.discard(shm)

    def _cleanup_all_shm(self) -> int:
        count = 0
        for shm in list(self._active_shm):
            count += 1
            try:
                shm.close()
            except Exception:
                pass
            try:
                shm.unlink()
            except Exception:
                pass
        self._active_shm.clear()
        return count

    async def close(self, timeout: float | None = None) -> None:
        """Safely shut down the runtime:
        1. Stop accepting new requests.
        2. Wait for in-flight extractions to complete up to `timeout`.
        3. If timeout expires, forcefully terminate running worker processes.
        4. Clean up executor and any orphaned SharedMemory segments.
        """
        if self._closed:
            return
        self._closed = True

        wait_timeout = timeout if timeout is not None else self.shutdown_timeout
        logger.info(
            "runtime_shutdown_started",
            extra={
                "in_flight": self._in_flight,
                "timeout_seconds": wait_timeout,
            },
        )

        # 1. Stop accepting new requests
        self._accepting = False

        # 2. Wait for in-flight tasks to drain
        drained = True
        if self._in_flight > 0:
            try:
                await asyncio.wait_for(self._drain_event.wait(), timeout=wait_timeout)
                logger.info(
                    "runtime_drain_completed",
                    extra={"in_flight": self._in_flight},
                )
            except TimeoutError:
                drained = False
                logger.warning(
                    "runtime_shutdown_timeout_exceeded",
                    extra={
                        "remaining_in_flight": self._in_flight,
                        "timeout_seconds": wait_timeout,
                    },
                )

        # 3. Shutdown executor and processes
        if self._owns_executor:
            if not drained:
                procs = getattr(self._executor, "_processes", None)
                if procs:
                    for proc in list(procs.values()):
                        try:
                            if proc.is_alive():
                                proc.terminate()
                        except Exception:
                            pass
                await asyncio.to_thread(
                    self._executor.shutdown, wait=True, cancel_futures=True
                )
            else:
                await asyncio.to_thread(
                    self._executor.shutdown, wait=True, cancel_futures=False
                )

        # 4. Clean up any remaining SharedMemory segments (failsafe)
        cleaned_shm = self._cleanup_all_shm()
        if cleaned_shm > 0:
            logger.info("runtime_shm_cleaned", extra={"cleaned_count": cleaned_shm})

        logger.info("runtime_shutdown_completed")
