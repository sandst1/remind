"""
Cross-encoder reranker for retrieval post-processing.

Requires the `rerank` extra: pip install "remind-mcp[rerank]"
"""

import io
import logging
import os
import sys
import time
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


def _detect_device() -> str:
    """Pick the best available device for PyTorch inference."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


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

        t_start = time.perf_counter()
        cached = _model_is_cached(self._model_name)
        if not cached:
            logger.info(f"Downloading reranker model: {self._model_name} (first time only)")

        device = _detect_device()
        logger.debug(f"Reranker device: {device}")

        saved_env = {}
        env_overrides = {
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TQDM_DISABLE": "1",
            "TRANSFORMERS_VERBOSITY": "error",
        }
        for key, val in env_overrides.items():
            saved_env[key] = os.environ.get(key)
            os.environ[key] = val

        # Redirect stderr at the fd level to suppress safetensors "Loading
        # weights" tqdm bar and sentence-transformers "LOAD REPORT" — both
        # write directly to the C-level stderr fd, bypassing Python logging.
        old_stderr = sys.stderr
        stderr_fd = sys.stderr.fileno()
        saved_fd = os.dup(stderr_fd)
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, stderr_fd)
            os.close(devnull)
            sys.stderr = io.StringIO()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._model = CrossEncoder(self._model_name, device=device)
        finally:
            os.dup2(saved_fd, stderr_fd)
            os.close(saved_fd)
            sys.stderr = old_stderr
            for key, old_val in saved_env.items():
                if old_val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_val
        t_total_ms = (time.perf_counter() - t_start) * 1000.0
        logger.debug(
            "Reranker timing: load_model=%.1fms (cached=%s, device=%s, model=%s)",
            t_total_ms,
            cached,
            device,
            self._model_name,
        )

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
        t_predict_start = time.perf_counter()
        raw_scores = self._model.predict(pairs)
        t_predict_ms = (time.perf_counter() - t_predict_start) * 1000.0

        import math
        t_post_start = time.perf_counter()
        results = []
        nan_count = 0
        for s in raw_scores:
            val = float(s)
            if math.isnan(val):
                nan_count += 1
                results.append(0.0)
            else:
                results.append(1.0 / (1.0 + math.exp(-val)))
        t_post_ms = (time.perf_counter() - t_post_start) * 1000.0

        if nan_count:
            logger.error(
                f"Reranker returned NaN for {nan_count}/{len(raw_scores)} scores "
                f"(model={self._model_name}, device={getattr(self._model, 'device', '?')}). "
                f"Falling back to 0.0 for affected scores. "
                f"This may indicate a model/device compatibility issue."
            )

        logger.debug(
            "Reranker timing: predict=%.1fms postprocess=%.1fms docs=%d",
            t_predict_ms,
            t_post_ms,
            len(documents),
        )
        return results
