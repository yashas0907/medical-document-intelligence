"""Production-safe startup: cap BLAS/OpenMP threads BEFORE numpy/sklearn load.

Why: scikit-learn ships OpenBLAS, which by default spawns one thread per CPU
core. On machines with many cores this multiplies per-thread stack buffers and
can exhaust memory during TF-IDF matrix work (observed: OpenBLAS "Memory
allocation still failed after 10 retries" crashing the whole server).
Single-threaded BLAS is also faster for our small per-document matrices.
"""
import os

for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(var, "1")

from app.main import app  # noqa: E402,F401  (import after env is set)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
