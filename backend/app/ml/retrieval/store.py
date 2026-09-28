"""Retriever index persistence + rebuild.

Indexes are cached on disk per document (hash of chunk ids + embedding model).
Cache invalidation is explicit: index fingerprint = (pipeline_version,
embedding_model, chunk texts hash). Any pipeline/model change rebuilds.
"""
import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ml.retrieval.hybrid import HybridRetriever
from app.ml.versions import PIPELINE_VERSION

log = get_logger(__name__)


def _index_dir() -> Path:
    s = get_settings()
    p = Path(s.storage_root) / "indexes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fingerprint(chunks: list[dict], embedding_model: str) -> str:
    h = hashlib.sha256()
    h.update(PIPELINE_VERSION.encode())
    h.update(embedding_model.encode())
    for c in chunks:
        h.update(c["chunk_id"].encode())
        h.update(c["text"].encode("utf-8", "ignore"))
    return h.hexdigest()


def build_retriever_from_chunks(chunks: list[dict], embedding_model: str) -> HybridRetriever:
    r = HybridRetriever()
    r.fit(chunks)
    return r


def get_document_retriever(document_id: str, chunks: list[dict], embedding_model: str) -> HybridRetriever:
    """Memoized in-process retriever with fingerprint validation."""
    cache = getattr(get_document_retriever, "_cache", None)
    if cache is None:
        cache = get_document_retriever._cache = {}

    fp = _fingerprint(chunks, embedding_model)
    cached = cache.get(document_id)
    if cached and cached[0] == fp:
        return cached[1]

    r = build_retriever_from_chunks(chunks, embedding_model)
    cache[document_id] = (fp, r)
    if len(cache) > 16:  # simple LRU cap
        oldest = next(iter(cache))
        cache.pop(oldest)
    return r
