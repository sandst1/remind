"""
Local embedding provider using fastembed (ONNX-based, no torch required).

This is the default embedding provider - works offline with no API keys.
"""

import io
import logging
import os
import sys
import time
import warnings
from typing import Optional

from remind.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Default model - small, fast, good quality for retrieval
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Model dimensions lookup
MODEL_DIMENSIONS = {
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "sentence-transformers/all-mpnet-base-v2": 768,
}


def _model_is_cached(model_name: str) -> bool:
    """Check if a model is already downloaded locally."""
    try:
        from huggingface_hub import try_to_load_from_cache
        result = try_to_load_from_cache(model_name, "config.json")
        return isinstance(result, str)
    except Exception:
        return False


class LocalEmbedding(EmbeddingProvider):
    """
    Local embedding provider using fastembed.
    
    Uses ONNX runtime for fast CPU inference without PyTorch.
    Models are downloaded from HuggingFace on first use.
    
    Default model is all-MiniLM-L6-v2 (384 dimensions).
    """
    
    def __init__(self, model: str = DEFAULT_MODEL):
        try:
            import fastembed  # noqa: F401
        except ImportError:
            raise ImportError(
                "fastembed package is required for local embeddings. "
                "Install with: pip install fastembed"
            )
        
        self._model_name = model
        self._model: Optional[object] = None
        self._dims = MODEL_DIMENSIONS.get(model, 384)
    
    def _load_model(self):
        """Lazy-load the embedding model."""
        from fastembed import TextEmbedding
        
        t_start = time.perf_counter()
        cached = _model_is_cached(self._model_name)
        if not cached:
            logger.info(f"Downloading embedding model: {self._model_name} (first time only)")
        
        # Suppress noisy output during model loading
        saved_env = {}
        env_overrides = {
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TQDM_DISABLE": "1",
        }
        for key, val in env_overrides.items():
            saved_env[key] = os.environ.get(key)
            os.environ[key] = val
        
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
                self._model = TextEmbedding(model_name=self._model_name)
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
            "Local embedding timing: load_model=%.1fms (cached=%s, model=%s)",
            t_total_ms,
            cached,
            self._model_name,
        )
    
    async def embed(self, text: str) -> list[float]:
        """Generate an embedding for a single text."""
        if self._model is None:
            self._load_model()
        
        # fastembed returns a generator, convert to list
        embeddings = list(self._model.embed([text]))
        return embeddings[0].tolist()
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        
        if self._model is None:
            self._load_model()
        
        # fastembed handles batching internally
        embeddings = list(self._model.embed(texts))
        return [e.tolist() for e in embeddings]
    
    @property
    def dimensions(self) -> int:
        return self._dims
    
    @property
    def name(self) -> str:
        return f"local/{self._model_name}"
