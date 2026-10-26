"""Сборка обучающей/тестовой выборки: карточки каталога + эталонная разметка data/gold/*.csv."""
import csv
from pathlib import Path

import numpy as np

from ..catalog import Catalog
from ..config import CATALOG_PATH, GOLD_NEW_PATH, GOLD_PATH, NEW_PRODUCTS_PATH
from ..taxonomy import work_type_ids


def load_gold(path: Path) -> dict[int, dict]:
    with open(path, encoding="utf-8") as f:
        return {int(r["id"]): r for r in csv.DictReader(f, delimiter=";")}


def build(catalog_path: Path, gold_path: Path):
    cat = Catalog.load(catalog_path)
    gold = load_gold(gold_path)
    classes = work_type_ids()
    ids, texts, Y, kinds, groups, products = [], [], [], [], [], []
    for p in cat:
        g = gold.get(int(p["id"]))
        if g is None:
            continue
        labels = set(filter(None, g["work_types"].split("|")))
        unknown = labels - set(classes)
        assert not unknown, f"неизвестные виды работ в эталоне: {unknown}"
        products.append(p)
        ids.append(int(p["id"]))
        texts.append(p["_text"])
        Y.append([int(c in labels) for c in classes])
        kinds.append(g["kind"])
        groups.append(g["subtype"])
    return {"catalog": cat, "products": products, "ids": ids, "texts": texts, "Y": np.array(Y, dtype=int), "kinds": kinds,
            "groups": groups, "classes": classes}


def default_sets():
    return CATALOG_PATH, GOLD_PATH, NEW_PRODUCTS_PATH, GOLD_NEW_PATH

