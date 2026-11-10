import asyncio
from multiprocessing.shared_memory import SharedMemory
import threading
import time
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


@pytest.mark.asyncio
async def test_runtime_graceful_shutdown_drains_in_flight():
    started = threading.Event()
    finish_work = threading.Event()

    def slow_extraction(shm_name: str, size: int) -> tuple[str, int]:
        started.set()
        finish_work.wait(timeout=2)
        return "## Página 1", 1

    executor = ThreadPoolExecutor(max_workers=1)
    runtime = ExtractionRuntime(
        workers=1,
        queue_size=1,
        queue_wait_timeout=0,
        extraction_timeout=3,
        executor=executor,
        extraction_function=slow_extraction,
        shutdown_timeout=3.0,
    )

    in_flight_task = asyncio.create_task(runtime.extract(b"test pdf content"))
    assert await asyncio.to_thread(started.wait, 1)

    assert runtime.in_flight == 1

    # Initiate close while the task is still running
    close_task = asyncio.create_task(runtime.close())
    await asyncio.sleep(0.05)

    # 1. New requests should be rejected immediately during shutdown
    assert not runtime.accepting
    with pytest.raises(ExtractionOverloadedError, match="deteniendo"):
        await runtime.extract(b"rejected")

    # 2. In-flight task is still running
    assert not in_flight_task.done()

    # 3. Allow in-flight task to finish
    finish_work.set()

    # 4. In-flight task completes cleanly
    result = await in_flight_task
    assert result == ("## Página 1", 1)

    # 5. Close task completes cleanly
    await close_task
    assert runtime.in_flight == 0
    assert len(runtime._active_shm) == 0

    executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_runtime_shutdown_timeout_forces_termination_and_cleans_shm():
    started = threading.Event()

    def hanging_extraction(shm_name: str, size: int) -> tuple[str, int]:
        started.set()
        time.sleep(5)  # simulate hung worker
        return "never", 0

    executor = ThreadPoolExecutor(max_workers=1)
    runtime = ExtractionRuntime(
        workers=1,
        queue_size=1,
        queue_wait_timeout=0,
        extraction_timeout=5,
        executor=executor,
        extraction_function=hanging_extraction,
        shutdown_timeout=0.2,
    )

    task = asyncio.create_task(runtime.extract(b"hang"))
    assert await asyncio.to_thread(started.wait, 1)

    start_time = time.perf_counter()
    # close should enforce the 0.2s timeout and not block for 5 seconds
    await runtime.close(timeout=0.2)
    elapsed = time.perf_counter() - start_time

    assert elapsed < 1.0, f"Shutdown took too long: {elapsed}s"
    assert len(runtime._active_shm) == 0

    # Clean up background hanging task
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    executor.shutdown(wait=False)
