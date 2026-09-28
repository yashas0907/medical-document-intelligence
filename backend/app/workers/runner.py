"""In-process async job worker.

Decision: FastAPI BackgroundTasks + a bounded ThreadPoolExecutor give real
asynchronous processing without a broker (Celery/RQ) while keeping the job
semantics (queued → processing → completed/failed). For a single-node
deployment this is the right complexity level; the service boundary
(process_document) is broker-agnostic if Celery is added later.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("worker")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            s = get_settings()
            _executor = ThreadPoolExecutor(
                max_workers=max(1, s.worker_concurrency),
                thread_name_prefix="medintel-worker",
            )
            log.info("worker pool initialized size=%s", s.worker_concurrency)
        return _executor


def submit(fn, *args, **kwargs):
    return get_executor().submit(fn, *args, **kwargs)


def shutdown_executor() -> None:
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
