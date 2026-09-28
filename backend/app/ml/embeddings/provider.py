"""Embedding provider abstraction.

local: TF-IDF (scikit-learn) per-document index — deterministic, offline,
  zero-cost, works well for single-document/corpus retrieval at this scale.
  Honest limitation: no cross-document semantics; upgrade path documented.
openai: OpenAI-compatible /embeddings endpoint (config-driven). Dimension
  mismatches trigger explicit reindex, never silent corruption.
"""
from typing import Protocol

from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)


class EmbeddingProvider(Protocol):
    name: str
    model_id: str
    dimension: int | None

    def fit(self, corpus: list[str]) -> None: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class LocalTfidfEmbedder:
    """TF-IDF vectors as embeddings. fit() must be called on the corpus first."""

    def __init__(self, model_id: str = "medintel-tfidf-v1"):
        self.name = "local"
        self.model_id = model_id
        self._vec = None
        self._matrix = None
        self.dimension: int | None = None

    def fit(self, corpus: list[str]) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vec = TfidfVectorizer(
            max_features=30_000,
            ngram_range=(1, 2),
            sublinear_tf=True,
            stop_words="english",
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-/]{1,30}\b",
        )
        if corpus:
            self._matrix = self._vec.fit_transform(corpus)
            self.dimension = len(self._vec.vocabulary_)
        else:
            self._matrix = None
            self.dimension = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._vec is None:
            raise ServiceUnavailableError("Embedder not fitted")
        m = self._vec.transform(texts)
        return [m[i].toarray()[0].tolist() for i in range(m.shape[0])]

    def embed_query(self, text: str) -> list[float]:
        if self._vec is None:
            raise ServiceUnavailableError("Embedder not fitted")
        m = self._vec.transform([text])
        return m[0].toarray()[0].tolist()

    def corpus_matrix(self):
        if self._matrix is None:
            raise ServiceUnavailableError("Embedder not fitted on corpus")
        return self._matrix


class OpenAICompatibleEmbedder:
    """Remote embeddings via any OpenAI-compatible /embeddings endpoint."""

    def __init__(self, model_id: str, api_base: str, api_key: str, batch_size: int = 64):
        import httpx

        self.name = "openai"
        self.model_id = model_id
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._batch = batch_size
        self._http = httpx.Client(timeout=60)
        self.dimension: int | None = None

    def fit(self, corpus: list[str]) -> None:
        pass  # stateless remote model

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            resp = self._http.post(
                f"{self._api_base}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model_id, "input": batch},
            )
            if resp.status_code != 200:
                raise ServiceUnavailableError(
                    f"Embedding API error {resp.status_code}",
                    details={"body": resp.text[:300]},
                )
            data = resp.json()["data"]
            out.extend([d["embedding"] for d in data])
        if out and self.dimension is None:
            self.dimension = len(out[0])
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


def build_embedder(settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        if not settings.embedding_api_key or not settings.embedding_api_base:
            raise ServiceUnavailableError(
                "EMBEDDING_PROVIDER=openai requires EMBEDDING_API_KEY and EMBEDDING_API_BASE"
            )
        return OpenAICompatibleEmbedder(
            settings.embedding_model, settings.embedding_api_base, settings.embedding_api_key
        )
    return LocalTfidfEmbedder(settings.embedding_model)
