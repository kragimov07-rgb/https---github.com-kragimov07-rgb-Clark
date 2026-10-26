"""Сборка реального каталога Максидома в формат сервиса + эталонная разметка.

Вход (data/real/raw/):
  products_final.json        — выгрузка организаторов (88 790 карточек)
  export_yandex_spb.xml      — YML-фид сайта (дерево категорий, цена СПб, наличие, фото)
Выход (data/real/):
  products.json              — карточки в формате сервиса (без отложенной выборки)
  new_products.json          — отложенная выборка «новых товаров» (3%), в обучении не участвует
  labels.csv / labels_new.csv — эталон id;subtype(=категория);kind;work_types
  category_map.csv           — таблица «категория -> виды работ» для проверки командой

Запуск: python -m scripts.build_real_catalog
"""
import csv
import json
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.real_category_map import label  # noqa: E402

RAW = ROOT / "data" / "real" / "raw"
OUT = ROOT / "data" / "real"
NUM = r"(\d+(?:[.,]\d+)?)"


def load_feed():
    shop = ET.parse(RAW / "export_yandex_spb.xml").getroot().find("shop")
    cats = {c.get("id"): (c.text, c.get("parentId")) for c in shop.find("categories")}
    by_cod = {}
    for of in shop.find("offers"):
        m = re.search(r"/(\d{6,})/?$", of.findtext("url") or "")
        if m:
            by_cod[m.group(1)] = of
    return cats, by_cod


def cat_path(cats, cid):
    out, guard = [], 0
    while cid and cid in cats and guard < 10:
        out.append((cid, cats[cid][0]))
        cid = cats[cid][1]
        guard += 1
    return out[::-1]


def clean_chars(chars):
    out, seen = [], set()
    for c in chars or []:
        name = " ".join(str(c.get("name", "")).split())
        value = " ".join(str(c.get("value", "")).split())
        if not name or not value or name == "Маркетинговое описание товара" or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "value": value})
    return out


def num(s):
    m = re.search(NUM, str(s or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def main():
    data = json.loads((RAW / "products_final.json").read_text(encoding="utf-8"))["products"]
    cats, by_cod = load_feed()
    by_name = defaultdict(list)
    for cid, (n, _) in cats.items():
        by_name[n].append(cid)

    products, gold, catmap = [], [], defaultdict(lambda: {"n": 0})
    for p in data:
        (cat_id, cat_name), = p["categories"].items()
        offer = by_cod.get(str(p["cod_good"]))
        if offer is not None:
            path = cat_path(cats, offer.findtext("categoryId"))
        else:
            ids = by_name.get(cat_name, [])
            path = cat_path(cats, ids[0]) if ids else []
        if not path or path[-1][1] != cat_name:
            path = path + [(cat_id, cat_name)] if path else [("0", "Без раздела"), (cat_id, cat_name)]
        names = [n for _, n in path]
        chars = clean_chars(p.get("characteristics"))
        ch = {c["name"]: c["value"] for c in chars}
        parea = num(ch.get("Площадь покрытия упаковкой")) or num(re.search(NUM + r"\s*м2", ch.get("В упаковке", "")) and
                                                              re.search(NUM + r"\s*м2", ch.get("В упаковке", "")).group(0))
        price = float(p.get("price") or 0)
        result_price = float(offer.findtext("price")) if offer is not None and offer.findtext("price") else price
        old = offer.findtext("oldprice") if offer is not None else None
        item = {
            "id": p["id"], "sku": str(p["cod_good"]), "cod_good": str(p["cod_good"]), "name": p["name"],
            "marketing_description": p.get("marketing_description") or "",
            "description": (p.get("description") or "").replace("<br>", "; "),
            "url_key": p.get("url_key"), "price": price, "result_price": result_price, "currency": "RUB",
            "old_price": float(old) if old else None, "special_price_active": bool(old),
            "brand": p.get("brand"), "collection": p.get("collection"), "country": p.get("country"),
            "categories": {str(cat_id): cat_name},
            "categories_tree": [{"id": cid, "name": n, "depth": i + 1} for i, (cid, n) in enumerate(path)],
            "unit": p.get("unit") or "шт.", "weight": p.get("weight"), "characteristics": chars,
            "quantity_in_package": num(ch.get("Количество в упаковке")), "package_area": parea,
            "price_per_m2": round(result_price / parea, 2) if parea else None,
            "in_stock": (offer.get("available") == "true") if offer is not None else None,
            "stocks": [], "picture": offer.findtext("picture") if offer is not None else None,
            "ratings": {"rating": None}, "recsys_rating": None, "status": True,
        }
        products.append(item)
        wt, kind = label(cat_name, names, p["name"])
        key = " / ".join(names)
        catmap[key].update(category=cat_name, path=key, work_types="|".join(wt) if wt is not None else "—",
                           kind=kind or "—")
        catmap[key]["n"] += 1
        if wt is not None:
            gold.append({"id": p["id"], "subtype": cat_name, "kind": kind, "work_types": "|".join(wt)})

    # отложенная выборка новых товаров: 3% размеченных, стратифицированно по факту наличия меток
    rng = random.Random(42)
    labeled_ids = [g["id"] for g in gold]
    holdout = set(rng.sample(labeled_ids, k=int(len(labeled_ids) * 0.03)))
    main_p = [p for p in products if p["id"] not in holdout]
    new_p = [p for p in products if p["id"] in holdout]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "products.json").write_text(json.dumps(main_p, ensure_ascii=False), encoding="utf-8")
    (OUT / "new_products.json").write_text(json.dumps(new_p, ensure_ascii=False), encoding="utf-8")
    for fname, rows in (("labels.csv", [g for g in gold if g["id"] not in holdout]),
                        ("labels_new.csv", [g for g in gold if g["id"] in holdout])):
        with open(OUT / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "subtype", "kind", "work_types"], delimiter=";")
            w.writeheader()
            w.writerows(rows)
    with open(OUT / "category_map.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["path", "category", "products", "work_types", "kind", "verified_by"])
        for v in sorted(catmap.values(), key=lambda v: v["path"]):
            w.writerow([v["path"], v["category"], v["n"], v["work_types"], v["kind"], ""])

    in_scope = sum(1 for g in gold if g["work_types"])
    multi = sum(1 for g in gold if "|" in g["work_types"])
    print(f"products={len(products)} labeled={len(gold)} in_scope={in_scope} multi_label={multi} "
          f"holdout={len(new_p)} joined_feed={sum(1 for p in products if p['in_stock'] is not None)}")
    print(Counter(w for g in gold for w in g["work_types"].split("|") if w).most_common())


if __name__ == "__main__":
    main()
