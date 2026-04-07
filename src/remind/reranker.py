"""
Cross-encoder reranker for retrieval post-processing.

Requires the `rerank` extra: pip install "remind-mcp[rerank]"
"""

import logging
import os
import warnings
from typing import Optional

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    'Reranking requires sentence-transformers. '
    'Install with: pip install "remind-mcp[rerank]"'
)


def _model_is_cached(model_name: str) -> bool:
    """Check if a HuggingFace model is already downloaded locally."""
    try:
        from huggingface_hub import try_to_load_from_cache
        result = try_to_load_from_cache(model_name, "config.json")
        return isinstance(result, str)
    except Exception:
        return False


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

        cached = _model_is_cached(self._model_name)
        if not cached:
            logger.info(f"Downloading reranker model: {self._model_name} (first time only)")

        saved_env = {}
        env_overrides = {
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TQDM_DISABLE": "1",
            "TRANSFORMERS_VERBOSITY": "error",
        }
        for key, val in env_overrides.items():
            saved_env[key] = os.environ.get(key)
            os.environ[key] = val

        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*unauthenticated.*")
                warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")

                noisy_loggers = [
                    logging.getLogger(name)
                    for name in ("huggingface_hub", "sentence_transformers", "transformers")
                ]
                old_levels = [lg.level for lg in noisy_loggers]
                for lg in noisy_loggers:
                    lg.setLevel(logging.ERROR)
                try:
                    self._model = CrossEncoder(self._model_name)
                finally:
                    for lg, lvl in zip(noisy_loggers, old_levels):
                        lg.setLevel(lvl)
        finally:
            for key, old_val in saved_env.items():
                if old_val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_val

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
