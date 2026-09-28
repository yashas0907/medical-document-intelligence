"""Hybrid retrieval: TF-IDF cosine (semantic-ish) + BM25 (lexical), fused via RRF.

Why hybrid: BM25 nails exact medical terminology (drug names, "HbA1c", lab
names) that dense-ish embeddings can miss; TF-IDF handles paraphrase. RRF is
robust fusion without score-scale gymnastics.

The index is per-document (documents are private per user â€” no cross-user
leakage possible by construction).
"""
import re
from dataclasses import dataclass

from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger
from app.ml.embeddings.provider import LocalTfidfEmbedder

log = get_logger(__name__)

RRF_K = 60


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    page_number: int
    section_id: str | None
    section_title: str | None
    text: str
    is_table_chunk: bool
    vector_score: float
    lexical_score: float
    fused_rank: int
    fused_score: float


class HybridRetriever:
    """Build per-document index from stored chunks; query hybrid."""

    def __init__(self):
        self._embedder = LocalTfidfEmbedder()
        self._bm25 = None
        self._chunk_ids: list[str] = []
        self._meta: list[dict] = []
        self._fitted = False
        self._doc_ids: set[str] = set()

    @property
    def chunk_count(self) -> int:
        return len(self._chunk_ids)

    @property
    def document_ids(self) -> set[str]:
        return set(self._doc_ids)

    def fit(self, chunks: list[dict]) -> None:
        """chunks: [{chunk_id, document_id, page_number, section_id, section_title,
        text, is_table_chunk}]"""
        from rank_bm25 import BM25Okapi

        if not chunks:
            self._fitted = True
            self._chunk_ids = []
            self._meta = []
            self._embedder.fit([])
            self._bm25 = None
            return
        self._chunk_ids = [c["chunk_id"] for c in chunks]
        self._meta = chunks
        self._doc_ids = {c["document_id"] for c in chunks}
        texts = [c["text"] for c in chunks]
        self._embedder.fit(texts)
        tokenized = [self._tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(tokenized)
        self._fitted = True

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def search(self, query: str, top_k: int = 6, min_vector: float = 0.02,
               doc_boost: bool = True) -> list[ScoredChunk]:
        if not self._fitted:
            raise ServiceUnavailableError("Retriever not fitted")
        if not self._chunk_ids or not query.strip():
            return []

        from app.ml.retrieval.query_expand import expand_query

        expanded = expand_query(query)
        # Vector leg — sparse-safe cosine (no full corpus densification:
        # densifying large corpora exhausts memory; sparse matvec is O(nnz))
        qv = self._embedder.embed_query(expanded)
        corpus = self._embedder.corpus_matrix()
        import numpy as np
        from scipy import sparse as sp

        q = np.asarray(qv).ravel()
        corpus_norm = sp.linalg.norm(corpus, axis=1) if sp.issparse(corpus) else np.linalg.norm(corpus, axis=1)
        corpus_norm = np.clip(corpus_norm, 1e-12, None)
        q_norm = max(float(np.linalg.norm(q)), 1e-12)
        sims = (corpus @ q) / (corpus_norm * q_norm)
        vec_scores = np.clip(np.asarray(sims).ravel(), 0.0, 1.0)

        # Lexical leg â€” exact-term boost: query terms present verbatim matter
        tokens = self._tokenize(expanded)
        lex_scores = [0.0] * len(self._chunk_ids)
        if self._bm25 is not None and tokens:
            lex_scores = list(self._bm25.get_scores(tokens))
            # coverage bonus: fraction of query tokens present in chunk (incl. section title)
            qtoks = {t for t in tokens if len(t) > 2}
            for i, meta in enumerate(self._meta):
                chunk_toks = set(self._tokenize(meta["text"]))
                title_toks = set(self._tokenize(meta.get("section_title") or ""))
                chunk_toks |= title_toks
                if qtoks:
                    cov = len(qtoks & chunk_toks) / len(qtoks)
                    lex_scores[i] += 6.0 * cov  # comparable scale to bm25 scores

        # RRF fusion
        vec_order = sorted(range(len(vec_scores)), key=lambda i: vec_scores[i], reverse=True)
        lex_order = sorted(range(len(lex_scores)), key=lambda i: lex_scores[i], reverse=True)
        vec_rank = {idx: r for r, idx in enumerate(vec_order)}
        lex_rank = {idx: r for r, idx in enumerate(lex_order)}

        fused: list[tuple[float, int]] = []
        for i in range(len(self._chunk_ids)):
            score = 1.0 / (RRF_K + 1 + vec_rank[i]) + 1.0 / (RRF_K + 1 + lex_rank[i])
            fused.append((score, i))
        fused.sort(reverse=True)

        results: list[ScoredChunk] = []
        for rank, (fscore, i) in enumerate(fused[:top_k]):
            meta = self._meta[i]
            # guard: zero-relevance chunks must not surface
            if vec_scores[i] < min_vector and lex_scores[i] <= 0.0:
                continue
            results.append(
                ScoredChunk(
                    chunk_id=self._chunk_ids[i],
                    document_id=meta["document_id"],
                    page_number=meta["page_number"],
                    section_id=meta.get("section_id"),
                    section_title=meta.get("section_title"),
                    text=meta["text"],
                    is_table_chunk=meta.get("is_table_chunk", False),
                    vector_score=round(float(vec_scores[i]), 4),
                    lexical_score=round(float(lex_scores[i]), 4),
                    fused_rank=rank + 1,
                    fused_score=round(fscore, 6),
                )
            )
        return results


