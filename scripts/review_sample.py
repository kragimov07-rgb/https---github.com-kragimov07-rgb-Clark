"""Выгрузка образца каталога для независимой ручной разметки двумя участниками команды.

Каждый разметчик заполняет свою колонку кодами видов работ через «|» (пусто — вне ремонта),
не глядя на колонку эталона (её можно скрыть в Excel). Затем: python -m eval.agreement data/gold/review_sample.csv

Запуск: python -m scripts.review_sample [--n 300]
"""
import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.catalog import Catalog, char_map, category_path  # noqa: E402
from app.config import CATALOG_PATH, GOLD_DIR, GOLD_PATH  # noqa: E402
from app.ml.dataset import load_gold  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default=str(GOLD_DIR / "review_sample.csv"))
    a = ap.parse_args()
    cat = Catalog.load(CATALOG_PATH)
    gold = load_gold(GOLD_PATH)
    by_sub = defaultdict(list)
    for pid, g in gold.items():
        by_sub[g["subtype"]].append(pid)
    rng = random.Random(7)
    # ремонтные товары важнее: 80% выборки — из размеченных видами работ, 20% — вне ремонта
    rep = [pid for pid, g in gold.items() if g["work_types"] and pid in cat.products]
    non = [pid for pid, g in gold.items() if not g["work_types"] and pid in cat.products]
    if len(by_sub) > a.n:
        ids = rng.sample(rep, min(len(rep), int(a.n * 0.8))) + rng.sample(non, min(len(non), a.n - int(a.n * 0.8)))
    else:
        per = max(1, a.n // len(by_sub))
        ids = [pid for subs in by_sub.values() for pid in rng.sample(subs, min(per, len(subs)))]
    rng.shuffle(ids)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "name", "category", "description", "characteristics", "gold", "annotator_a", "annotator_b"])
        for pid in ids[: a.n]:
            p = cat.get(pid)
            w.writerow([pid, p["name"], " / ".join(category_path(p)), p.get("description", ""),
                        "; ".join(f"{k}: {v}" for k, v in char_map(p).items()), gold[pid]["work_types"], "", ""])
    print(f"{min(a.n, len(ids))} товаров -> {a.out}")


if __name__ == "__main__":
    main()
