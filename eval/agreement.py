"""Согласованность ручной разметки: каппа Коэна по каждому виду работ между двумя разметчиками
и согласие каждого разметчика с эталоном. Расхождения выводятся для разбора и уточнения правил.

Запуск: python -m eval.agreement data/gold/review_sample.csv
"""
import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import cohen_kappa_score, f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.taxonomy import work_type_ids, work_type_name  # noqa: E402


def vec(cell, classes):
    s = {x.strip() for x in (cell or "").split("|") if x.strip()}
    return [int(c in s) for c in classes]


def main(path):
    classes = work_type_ids()
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig"), delimiter=";") if r["annotator_a"] or r["annotator_b"]]
    if not rows:
        print("колонки annotator_a / annotator_b не заполнены")
        return
    A = np.array([vec(r["annotator_a"], classes) for r in rows])
    B = np.array([vec(r["annotator_b"], classes) for r in rows])
    G = np.array([vec(r["gold"], classes) for r in rows])
    print(f"товаров: {len(rows)}")
    print(f"micro-F1 A vs B: {f1_score(A, B, average='micro', zero_division=0):.3f}")
    print(f"micro-F1 A vs эталон: {f1_score(G, A, average='micro', zero_division=0):.3f};"
          f" B vs эталон: {f1_score(G, B, average='micro', zero_division=0):.3f}")
    print("\nкаппа Коэна по видам работ (A vs B):")
    for i, c in enumerate(classes):
        if A[:, i].sum() + B[:, i].sum() == 0:
            continue
        k = cohen_kappa_score(A[:, i], B[:, i]) if len(set(A[:, i]) | set(B[:, i])) > 1 else 1.0
        print(f"  {work_type_name(c):45} {k:.2f}")
    print("\nрасхождения A/B:")
    for r, a, b in zip(rows, A, B):
        if (a != b).any():
            print(f"  {r['id']} {r['name'][:60]} | A={r['annotator_a']} | B={r['annotator_b']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/gold/review_sample.csv")
