"""Мок API стенда (формат из описания кейса) поверх тестового каталога.

Нужен, чтобы демонстрировать полный цикл «загрузка каталога через API -> ML-разметка» без доступа к стенду.
Отдаёт отложенные «новые» товары выбранного набора данных (new_products.json), которых нет в обучающем каталоге.
"""
import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from .config import DATA_DIR, NEW_PRODUCTS_PATH

router = APIRouter(prefix="/stand/api", tags=["mock-stand"])

LIST_FIELDS_EXCLUDED = {"description", "weight", "characteristics", "meta_title", "meta_description", "updated_at"}


@lru_cache
def _data():
    products = json.loads(NEW_PRODUCTS_PATH.read_text(encoding="utf-8"))
    tree_f, regions_f = DATA_DIR / "categories_tree.json", DATA_DIR / "regions.json"
    tree = json.loads(tree_f.read_text(encoding="utf-8")) if tree_f.exists() else build_tree(products)
    regions = json.loads(regions_f.read_text(encoding="utf-8")) if regions_f.exists() else {"data": [
        {"id": 1, "code": "spb", "name": "Санкт-Петербург", "oracle_cod_city": 1, "priority": 0, "status": True,
         "is_default": True, "warehouses_count": 1}]}
    return products, tree, regions


def build_tree(products):
    """Дерево категорий (2 уровня: корень -> листовая категория) из categories_tree товаров."""
    roots, counts = {}, {}
    for p in products:
        path = p.get("categories_tree") or []
        if not path:
            continue
        r, leaf = path[0], path[-1]
        node = roots.setdefault(str(r["id"]), {"id": r["id"], "parent_id": 1, "name": r["name"], "url_key": f"cat-{r['id']}",
                                              "status": True, "depth_level": 1, "product_count": 0, "children": {}})
        counts[str(leaf["id"])] = counts.get(str(leaf["id"]), 0) + 1
        node["children"].setdefault(str(leaf["id"]), {"id": leaf["id"], "parent_id": r["id"], "name": leaf["name"],
                                                       "url_key": f"cat-{leaf['id']}", "status": True, "depth_level": 2,
                                                       "children": []})
    data = []
    for node in roots.values():
        kids = list(node["children"].values())
        for k in kids:
            k["product_count"] = k["product_count_all_children"] = counts[str(k["id"])]
        node["children"] = kids
        node["product_count_all_children"] = sum(k["product_count"] for k in kids)
        data.append(node)
    return {"data": data}


@router.get("/catalog/categories/tree")
def categories_tree(category_id: str = "1", depth_level: int = 20, locale: str = "ru"):
    _, tree, _ = _data()
    return tree


@router.get("/catalog/categories")
def categories(parent_id: int = 1, depth_level: int = 2):
    _, tree, _ = _data()
    flat = []
    for c in tree["data"]:
        flat.append({k: v for k, v in c.items() if k != "children"})
        flat += [{k: v for k, v in ch.items() if k != "children"} for ch in c["children"]]
    return {"data": [c for c in flat if c["parent_id"] == parent_id]}


@router.get("/catalog/products")
def products(category_id: str, include_subsections: int = 0, include_categories_tree: int = 1,
             per_page: int = Query(20, le=100), page: int = 1, locale: str = "ru"):
    items, tree, _ = _data()
    ids = {category_id}
    if include_subsections:
        for c in tree["data"]:
            if c["id"] == category_id:
                ids |= {ch["id"] for ch in c["children"]}
    ids = {str(i) for i in ids}
    sel = [p for p in items if any(str(c["id"]) in ids for c in p.get("categories_tree") or [])]
    last = max(1, -(-len(sel) // per_page))
    chunk = sel[(page - 1) * per_page: page * per_page]
    out = []
    for p in chunk:
        q = {k: v for k, v in p.items() if k not in LIST_FIELDS_EXCLUDED}
        if not include_categories_tree:
            q.pop("categories_tree", None)
        out.append(q)
    return {"items": out, "properties": [], "generated_url": f"/cat-{category_id}/",
            "meta": {"total": len(sel), "per_page": per_page, "current_page": page, "last_page": last}}


@router.get("/catalog/products/{pid}")
def product(pid: int, locale: str = "ru"):
    items, _, _ = _data()
    for p in items:
        if p["id"] == pid:
            return {"data": p}
    raise HTTPException(404, "not found")


@router.get("/regions")
def regions():
    return _data()[2]
