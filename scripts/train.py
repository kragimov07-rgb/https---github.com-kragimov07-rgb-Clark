"""Обучение финальной модели матчинга на всём размеченном каталоге -> models/matcher.joblib.

Запуск: python -m scripts.train
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATASET, GOLD_PATH, CATALOG_PATH, MODEL_DIR  # noqa: E402
from app.ml.dataset import build  # noqa: E402
from app.ml.embed import default_embedder  # noqa: E402
from app.ml.features import Featurizer  # noqa: E402
from app.ml.matcher import WorkTypeMatcher  # noqa: E402


def train(catalog=CATALOG_PATH, gold=GOLD_PATH) -> WorkTypeMatcher:
    t0 = time.perf_counter()
    d = build(catalog, gold)
    emb = default_embedder()
    texts, E, Z = Featurizer(emb)(d["products"])
    emb.save()
    m = WorkTypeMatcher(d["classes"], "hybrid" if E is not None else "baseline")
    m.fit(texts, d["Y"], E, Z, kinds=d["kinds"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    m.save(MODEL_DIR / "matcher.joblib")
    meta = {"trained_at": datetime.now().isoformat(timespec="seconds"), "mode": m.mode, "products": len(texts),
            "classes": m.classes, "thresholds": dict(zip(m.classes, map(float, m.thresholds))),
            "fallback": m.fallback, "train_s": round(time.perf_counter() - t0, 2), "embedding_model": emb.model_name}
    meta["dataset"] = DATASET
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(json.dumps({k: meta[k] for k in ("mode", "products", "train_s", "fallback")}, ensure_ascii=False))
    return m


if __name__ == "__main__":
    train()
