import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from App.domain.exceptions import ExtractionOverloadedError
from App.infrastructure.extraction_runtime import ExtractionRuntime


@pytest.mark.asyncio
async def test_runtime_rejects_when_worker_and_queue_are_full():
    started = threading.Event()
    release = threading.Event()

    def blocking_extraction(shm_name: str, size: int) -> tuple[str, int]:
        started.set()
        release.wait(timeout=2)
        return "## Página 1", 1

    executor = ThreadPoolExecutor(max_workers=1)
    runtime = ExtractionRuntime(
        workers=1,
        queue_size=0,
        queue_wait_timeout=0,
        extraction_timeout=2,
        executor=executor,
        extraction_function=blocking_extraction,
    )

    first = asyncio.create_task(runtime.extract(b"first"))
    assert await asyncio.to_thread(started.wait, 1)
    try:
        with pytest.raises(ExtractionOverloadedError):
            await runtime.extract(b"second")
    finally:
        release.set()

    assert await first == ("## Página 1", 1)
    await runtime.close()
    executor.shutdown(wait=True)
