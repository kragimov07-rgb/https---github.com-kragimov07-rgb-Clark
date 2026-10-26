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
from app.ml.dataset import load_gold  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "data" / "gold" / "review_sample.csv"))
    a = ap.parse_args()
    cat = Catalog.load(ROOT / "data" / "catalog" / "products.json")
    gold = load_gold(ROOT / "data" / "gold" / "labels.csv")
    by_sub = defaultdict(list)
    for pid, g in gold.items():
        by_sub[g["subtype"]].append(pid)
    rng = random.Random(7)
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
