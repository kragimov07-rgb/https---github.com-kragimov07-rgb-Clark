"""Загрузка каталога со стенда по API из описания кейса.

Алгоритм: дерево категорий (достаточная глубина) -> по каждой листовой категории список товаров
постранично до meta.last_page -> полная карточка /products/{id} (характеристики есть только в ней) ->
дедупликация по id (Bagisto), коды товаров хранятся строками.

Запуск: python -m scripts.ingest_catalog --base-url http://<стенд> --out data/catalog/real_products.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def leaf_categories(tree: list[dict]) -> list[dict]:
    out = []
    for c in tree:
        kids = c.get("children") or []
        if kids:
            out += leaf_categories(kids)
        elif c.get("status", True) and (c.get("product_count") or c.get("product_count_all_children") or 0) > 0:
            out.append(c)
    return out


def fetch_catalog(base_url: str, category_id: int = 1, max_products: int = 100000, per_page: int = 50,
                  skip_ids: set | None = None, timeout: float = 20.0) -> tuple[list[dict], list[str]]:
    log, seen, products = [], set(skip_ids or ()), []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as cli:
        tree = cli.get("/api/catalog/categories/tree",
                       params={"category_id": category_id, "depth_level": 20, "locale": "ru"}).json()["data"]
        leaves = leaf_categories(tree)
        log.append(f"категорий-листьев: {len(leaves)}")
        for cat in leaves:
            page, last = 1, 1
            while page <= last and len(products) < max_products:
                r = cli.get("/api/catalog/products", params={"category_id": cat["id"], "include_subsections": 0,
                                                             "include_categories_tree": 1, "per_page": per_page,
                                                             "page": page, "locale": "ru"})
                r.raise_for_status()
                body = r.json()
                last = body.get("meta", {}).get("last_page", 1)
                for item in body.get("items", []):
                    pid = int(item["id"])
                    if pid in seen:
                        continue
                    seen.add(pid)
                    full = cli.get(f"/api/catalog/products/{pid}", params={"locale": "ru"})
                    data = full.json().get("data", item) if full.status_code == 200 else item
                    data = {**item, **data}  # categories_tree есть только в списке
                    data["cod_good"] = str(data.get("cod_good", ""))
                    products.append(data)
                page += 1
            if len(products) >= max_products:
                break
        log.append(f"загружено товаров: {len(products)}")
    return products, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--category-id", type=int, default=1)
    ap.add_argument("--max-products", type=int, default=100000)
    ap.add_argument("--out", default="data/catalog/real_products.json")
    a = ap.parse_args()
    t = time.perf_counter()
    products, log = fetch_catalog(a.base_url, a.category_id, a.max_products)
    Path(a.out).write_text(json.dumps(products, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(log), f"\nсохранено в {a.out} за {time.perf_counter() - t:.1f} с", file=sys.stderr)


if __name__ == "__main__":
    main()
