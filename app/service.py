"""Индекс каталога: ML-разметка всех товаров + ручные привязки из админки (имеют приоритет над ML)."""
import json
import logging
import threading
import time

import numpy as np

from . import llm
from .catalog import Catalog, public
from .config import BINDINGS_PATH, CATALOG_PATH, MODEL_DIR
from .ml.embed import default_embedder
from .ml.features import Featurizer
from .ml.matcher import WorkTypeMatcher
from .taxonomy import rooms as taxonomy_rooms
from .taxonomy import work_type_ids, work_type_name

log = logging.getLogger(__name__)
MODEL_PATH = MODEL_DIR / "matcher.joblib"


def suitable_rooms(attrs: dict, work_types: list[str]) -> list[str]:
    """Помещения, для которых товар подходит, по признакам товара (правила справочника помещений)."""
    out = {"living", "bedroom", "hallway"}
    if attrs.get("moisture_resistant") or "waterproofing" in work_types or "plumbing" in work_types:
        out |= {"bathroom", "toilet", "kitchen"}
    if attrs.get("washable"):
        out |= {"kitchen", "kids", "hallway"}
    if attrs.get("kids_safe"):
        out.add("kids")
    if attrs.get("frost_resistant") or "insulation" in work_types:
        out.add("balcony")
    if not attrs.get("moisture_resistant") and not attrs.get("washable"):
        out.add("kids")
    if {"tiling", "waterproofing", "plumbing", "ventilation", "sealing"} & set(work_types):
        out |= {"bathroom", "toilet", "kitchen"}
    if "waterproofing" in work_types:
        out -= {"living", "bedroom", "hallway", "kids"}
    return sorted(out)


class Index:
    def __init__(self, catalog: Catalog | None = None, matcher: WorkTypeMatcher | None = None):
        self.lock = threading.Lock()
        self.catalog = catalog or Catalog.load(CATALOG_PATH)
        self.embedder = default_embedder()
        self.feat = Featurizer(self.embedder)
        self.matcher = matcher or self._load_or_train()
        self.classes = self.matcher.classes
        self.bindings = self._load_bindings()
        self.stats = {}
        self.annotate(list(self.catalog), use_cache=catalog is None and matcher is None)

    # ---------- модель ----------
    def _load_or_train(self) -> WorkTypeMatcher:
        if MODEL_PATH.exists():
            return WorkTypeMatcher.load(MODEL_PATH)
        log.warning("models/matcher.joblib не найден — обучаю модель на data/gold/labels.csv")
        from scripts.train import train
        return train()

    @staticmethod
    def _load_bindings() -> dict:
        if BINDINGS_PATH.exists():
            return {int(k): v for k, v in json.loads(BINDINGS_PATH.read_text(encoding="utf-8")).items()}
        return {}

    def _save_bindings(self):
        BINDINGS_PATH.write_text(json.dumps(self.bindings, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- разметка ----------
    def predict(self, products: list[dict]):
        texts, E, Z = self.feat(products)
        Yp, P, kinds, kconf = self.matcher.predict_all(texts, E, Z)
        return Yp, P, kinds, kconf, E

    @staticmethod
    def _signature() -> str:
        """Каталог и модель не менялись -> разметку можно взять из кэша."""
        parts = [f"{f.stat().st_size}:{int(f.stat().st_mtime)}" for f in (CATALOG_PATH, MODEL_PATH) if f.exists()]
        return "|".join(parts)

    def _cached_predict(self, products):
        """Разметка всего каталога с кэшем на диске (models/<набор>/annotations.npz)."""
        cache = MODEL_DIR / "annotations.npz"
        sig = self._signature()
        ids = np.array([int(p["id"]) for p in products])
        if cache.exists():
            z = np.load(cache, allow_pickle=False)
            if str(z["sig"]) == sig and np.array_equal(z["ids"], ids):
                from .ml.features import ml_text
                E = self.embedder.encode([ml_text(p) for p in products])
                return z["Yp"].astype(int), z["P"].astype(np.float32), list(z["kinds"]), z["kconf"], E
        Yp, P, kinds, kconf, E = self.predict(products)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(cache, sig=np.array(sig), ids=ids, Yp=Yp.astype(np.int8), P=P.astype(np.float16),
                 kinds=np.array(kinds), kconf=np.asarray(kconf, dtype=np.float32))
        return Yp, P, kinds, kconf, E

    def annotate(self, products: list[dict], use_cache: bool = False):
        t0 = time.perf_counter()
        if not products:
            return
        Yp, P, kinds, kconf, E = self._cached_predict(products) if use_cache else self.predict(products)
        for i, p in enumerate(products):
            p["_ml"] = {
                "work_types": [self.classes[c] for c in np.where(Yp[i])[0]],
                "proba": {self.classes[c]: round(float(P[i, c]), 4) for c in np.argsort(-P[i])[:6]},
                "kind": kinds[i], "kind_conf": round(float(kconf[i]), 3),
            }
            p["_emb"] = None if E is None else E[i]
            self._apply_binding(p)
        dt = time.perf_counter() - t0
        self.stats = {"products": len(self.catalog), "last_annotate_s": round(dt, 3),
                      "last_annotate_ms_per_product": round(1000 * dt / len(products), 3),
                      "embeddings": self.embedder.available}
        self.embedder.save()
        self._reindex()

    def _reindex(self):
        """Индексы выдачи: (вид работ, класс) -> товары; матрица эмбеддингов для поиска похожих."""
        self._cand = {}
        for p in self.catalog:
            for w in p.get("_wt", []):
                self._cand.setdefault((w, p["_kind"]), []).append(p)
        with_emb = [p for p in self.catalog if p.get("_emb") is not None]
        self._emb_items = with_emb
        self._emb_M = np.stack([p["_emb"] for p in with_emb]) if with_emb else None

    def _apply_binding(self, p):
        b = self.bindings.get(int(p["id"]))
        ml = p["_ml"]
        p["_wt"] = b["work_types"] if b and "work_types" in b else ml["work_types"]
        p["_kind"] = b.get("kind", ml["kind"]) if b else ml["kind"]
        p["_source"] = "manual" if b else "ml"
        p["_rooms"] = b.get("rooms") if b and b.get("rooms") else suitable_rooms(p["_attrs"], p["_wt"])

    def ingest(self, products: list[dict]) -> list[dict]:
        """Загрузка новых товаров: добавление в каталог и автоматическая разметка без ручной работы.
        Неоднозначные товары (вероятность у порога) уточняет локальная LLM, если она доступна."""
        from .ml import llm_refine
        with self.lock:
            added = [self.catalog.add(p) for p in products]
            self.annotate(added)
            if llm.available():
                for p in added:
                    P_row = np.array([p["_ml"]["proba"].get(c, 0.0) for c in self.classes])
                    if llm_refine.is_uncertain(P_row, self.matcher.thresholds):
                        refined = llm_refine.refine(p, P_row, self.classes)
                        if refined is not None:
                            p["_ml"]["llm"] = refined
                            p["_ml"]["work_types"] = refined
                            self._apply_binding(p)
                self._reindex()
        return [self.describe(p) for p in added]

    def bind(self, pid: int, work_types: list[str] | None, kind: str | None, rooms: list[str] | None):
        unknown = set(work_types or []) - set(self.classes)
        if unknown:
            raise ValueError(f"неизвестные виды работ: {sorted(unknown)}")
        b = {}
        if work_types is not None:
            b["work_types"] = work_types
        if kind:
            b["kind"] = kind
        if rooms:
            b["rooms"] = rooms
        with self.lock:
            self.bindings[int(pid)] = b
            self._save_bindings()
            self._apply_binding(self.catalog.get(pid))
            self._reindex()

    def unbind(self, pid: int):
        with self.lock:
            self.bindings.pop(int(pid), None)
            self._save_bindings()
            self._apply_binding(self.catalog.get(pid))
            self._reindex()

    # ---------- выдача ----------
    def candidates(self, work_type: str, kind: str) -> list[dict]:
        return self._cand.get((work_type, kind), [])

    def by_work_type(self, work_type: str, limit=50) -> list[dict]:
        items = [p for p in self.catalog if work_type in p.get("_wt", [])]
        items.sort(key=lambda p: -p["_ml"]["proba"].get(work_type, 0))
        return items[:limit]

    def similar(self, p: dict, k=5) -> list[dict]:
        if p.get("_emb") is None or self._emb_M is None:
            return []
        s = self._emb_M @ p["_emb"]
        idx = [i for i in np.argsort(-s)[:k + 1] if self._emb_items[i]["id"] != p["id"]][:k]
        return [{"id": self._emb_items[i]["id"], "name": self._emb_items[i]["name"], "similarity": round(float(s[i]), 3),
                 "work_types": self._emb_items[i]["_wt"]} for i in idx]

    def describe(self, p: dict, with_similar=False) -> dict:
        d = {
            "id": p["id"], "name": p["name"], "category": " / ".join(c["name"] for c in p.get("categories_tree") or []),
            "work_types": [{"id": w, "name": work_type_name(w), "proba": p["_ml"]["proba"].get(w)} for w in p["_wt"]],
            "kind": p["_kind"], "kind_conf": p["_ml"]["kind_conf"], "rooms": p["_rooms"],
            "rooms_named": [taxonomy_rooms().get(r, {}).get("name", r) for r in p["_rooms"]],
            "source": p["_source"], "ml": p["_ml"], "attributes": p["_attrs"],
            "price": p.get("result_price"), "unit": p.get("unit"),
        }
        if with_similar:
            d["similar"] = self.similar(p)
        return d


def card(p: dict) -> dict:
    return public(p)


_index: Index | None = None


def get_index() -> Index:
    global _index
    if _index is None:
        _index = Index()
    return _index


def all_work_types() -> list[dict]:
    return [{"id": w, "name": work_type_name(w)} for w in work_type_ids()]
