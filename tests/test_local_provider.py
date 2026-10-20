"""Local provider loading and failure cleanup without downloading a model."""

import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from remind.providers.local import LocalEmbedding, _model_is_cached


@pytest.mark.asyncio
async def test_local_embedding_loads_once_and_handles_batches(monkeypatch):
    constructed, requests = [], []
    class Model:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
        def embed(self, texts):
            requests.append(texts)
            return iter(np.array([len(text), 1.]) for text in texts)
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Model))
    import remind.providers.local as local
    monkeypatch.setattr(local, "_model_is_cached", lambda _: True)
    monkeypatch.setenv("TQDM_DISABLE", "original")
    monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
    provider = LocalEmbedding()
    assert await provider.embed_batch([]) == []
    assert not constructed
    assert await provider.embed("one") == [3., 1.]
    assert await provider.embed_batch(["two", "four"]) == [[3., 1.], [4., 1.]]
    assert len(constructed) == 1
    assert requests == [["one"], ["two", "four"]]
    assert provider.dimensions == 384
    assert provider.name.endswith("all-MiniLM-L6-v2")
    assert os.environ["TQDM_DISABLE"] == "original"
    assert "HF_HUB_DISABLE_PROGRESS_BARS" not in os.environ


@pytest.mark.asyncio
async def test_failed_model_load_restores_stderr_and_environment(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("Failed to load model")
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=broken))
    import remind.providers.local as local
    monkeypatch.setattr(local, "_model_is_cached", lambda _: False)
    monkeypatch.setenv("HF_HUB_DISABLE_PROGRESS_BARS", "original")
    monkeypatch.delenv("TQDM_DISABLE", raising=False)
    previous_stderr = sys.stderr
    with pytest.raises(RuntimeError, match="Failed to load"):
        await LocalEmbedding().embed("test")
    assert sys.stderr is previous_stderr
    assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "original"
    assert "TQDM_DISABLE" not in os.environ


@pytest.mark.parametrize("cache_result,expected", [("/cached/config.json", True), (None, False)])
def test_cache_detection(monkeypatch, cache_result, expected):
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(try_to_load_from_cache=lambda *args: cache_result))
    assert _model_is_cached("test-model") is expected


def test_cache_detection_failure_is_safe(monkeypatch):
    def broken(*args):
        raise OSError("Cache unavailable")
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(try_to_load_from_cache=broken))
    assert not _model_is_cached("test-model")
