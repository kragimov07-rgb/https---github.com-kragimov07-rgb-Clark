"""Эмбеддинги текста локальной моделью multilingual-e5 (MIT). Кэш на диске, без внешних API."""
import hashlib
import logging
from pathlib import Path

import numpy as np

from ..config import EMBED_MODEL, MODELS

log = logging.getLogger(__name__)


class Embedder:
    """Кэш хранится одной матрицей (keys + vectors) — быстро грузится и для сотен тысяч текстов."""

    def __init__(self, model_name: str = EMBED_MODEL, cache_path: Path = MODELS / "emb_cache.npz"):
        self.model_name = model_name
        self.cache_path = cache_path
        self._model = None
        self.available = True
        self._index: dict[str, int] = {}
        self._vecs: list[np.ndarray] = []
        self._dirty = False
        if cache_path.exists():
            z = np.load(cache_path, allow_pickle=False)
            if "keys" in z.files:
                keys, M = z["keys"], z["vecs"]
                self._index = {str(k): i for i, k in enumerate(keys)}
                self._vecs = [M]
        self._flat = None

    def _load(self):
        if self._model is None and self.available:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:  # модель не скачана / нет библиотеки — работаем на TF-IDF
                log.warning("Embedder unavailable: %s", e)
                self.available = False
        return self._model

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def _matrix(self):
        if self._flat is None or len(self._vecs) > 1:
            self._flat = np.concatenate(self._vecs) if self._vecs else np.zeros((0, 384), np.float32)
            self._vecs = [self._flat]
        return self._flat

    def encode(self, texts: list[str], batch_size: int = 128) -> np.ndarray | None:
        keys = [self._key(t) for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self._index))
        if missing:
            model = self._load()
            if model is None:
                return None
            text_of = dict(zip(keys, texts))
            vecs = model.encode([f"query: {text_of[k]}" for k in missing], batch_size=batch_size,
                                normalize_embeddings=True, show_progress_bar=len(missing) > 5000).astype(np.float32)
            start = len(self._index)
            for i, k in enumerate(missing):
                self._index[k] = start + i
            self._vecs.append(vecs)
            self._flat = None
            self._dirty = True
        M = self._matrix()
        return M[[self._index[k] for k in keys]]

    def save(self):
        if not self._dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        keys = np.array(sorted(self._index, key=self._index.get))
        np.savez(self.cache_path, keys=keys, vecs=self._matrix())
        self._dirty = False


_default: Embedder | None = None


def default_embedder() -> Embedder:
    global _default
    if _default is None:
        _default = Embedder()
    return _default
