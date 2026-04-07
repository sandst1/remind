"""
Cross-encoder reranker for retrieval post-processing.

Requires the `rerank` extra: pip install "remind-mcp[rerank]"
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    'Reranking requires sentence-transformers. '
    'Install with: pip install "remind-mcp[rerank]"'
)


class Reranker:
    """Scores query-document relevance using a cross-encoder model.

    The model is loaded lazily on first call to :meth:`score` so that
    construction is cheap and import-time side effects are avoided.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            raise ImportError(_INSTALL_HINT)

        self._model_name = model_name
        self._model: Optional[object] = None

    def _load_model(self):
        from sentence_transformers import CrossEncoder

        logger.info(f"Loading reranker model: {self._model_name}")
        self._model = CrossEncoder(self._model_name)

    def score(self, query: str, documents: list[str]) -> list[float]:
        """Score each document's relevance to *query*.

        Returns a list of floats in [0, 1] (sigmoid-normalized) in the
        same order as *documents*.
        """
        if not documents:
            return []

        if self._model is None:
            self._load_model()

        pairs = [(query, doc) for doc in documents]
        raw_scores = self._model.predict(pairs)

        # ms-marco cross-encoders output logits; normalize to [0, 1]
        import math
        return [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]
