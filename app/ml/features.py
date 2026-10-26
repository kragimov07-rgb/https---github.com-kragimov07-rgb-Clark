"""Признаки для матчинга: эмбеддинги товара и zero-shot сходство со справочником видов работ.

Zero-shot: справочник (data/taxonomy.yaml) перечисляет типовые материалы каждого вида работ
(«плиточный клей», «затирка для швов», ...). Название и путь товара в каталоге сравниваются
с каждой фразой; признак вида работ = максимальное косинусное сходство. Это даёт модели знание
о видах товаров, которых не было в обучающей выборке.
"""
import re

import numpy as np

from ..catalog import category_path
from ..taxonomy import work_types
from .embed import Embedder


def ml_text(p: dict) -> str:
    """Текст для ML без бренда: бренд не определяет вид работ, но провоцирует переобучение."""
    text = p["_text"]
    brand = (p.get("brand") or {}).get("name")
    if brand:
        text = re.sub(re.escape(brand), " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def short_text(p: dict) -> str:
    name = p.get("name", "")
    brand = (p.get("brand") or {}).get("name")
    if brand:
        name = re.sub(re.escape(brand), " ", name, flags=re.IGNORECASE)
    path = category_path(p)
    return " ".join(f"{name}. {path[-1] if path else ''}".split())


def taxonomy_phrases() -> tuple[list[str], np.ndarray]:
    phrases, cls = [], []
    for i, w in enumerate(work_types()):
        items = [w["name"]] + [s.strip() for s in re.split(r"[,.;]", w["description"]) if len(s.strip()) > 3]
        for s in items:
            phrases.append(s)
            cls.append(i)
    return phrases, np.array(cls)


class Featurizer:
    def __init__(self, embedder: Embedder):
        self.emb = embedder
        phrases, self.phrase_cls = taxonomy_phrases()
        self.n_cls = int(self.phrase_cls.max()) + 1
        self.P = self.emb.encode(phrases)

    def __call__(self, products: list[dict]):
        texts = [ml_text(p) for p in products]
        E = self.emb.encode(texts)
        if E is None or self.P is None:
            return texts, None, None
        Es = self.emb.encode([short_text(p) for p in products])
        S = Es @ self.P.T
        Z = np.full((len(products), self.n_cls), -1.0, dtype=np.float32)
        for c in range(self.n_cls):
            Z[:, c] = S[:, self.phrase_cls == c].max(1)
        return texts, E, Z
