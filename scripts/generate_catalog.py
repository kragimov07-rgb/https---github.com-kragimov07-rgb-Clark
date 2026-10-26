"""Генерация тестового каталога в формате API стенда (Bagisto) + эталонной разметки.

Выход:
  data/catalog/categories_tree.json   — как GET /api/catalog/categories/tree
  data/catalog/products.json          — полные карточки, как GET /api/catalog/products/{id}
  data/catalog/regions.json           — как GET /api/regions
  data/catalog/new_products.json      — «новые» товары, которых нет в обучении (демо загрузки)
  data/gold/labels.csv                — эталон: id;subtype;kind;work_types (через |)

Запуск: python scripts/generate_catalog.py [--seed 42]
"""
import argparse
import csv
import json
import math
import random
import string
import zlib
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from catalog_spec import SUBTYPES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

CHAR_CODES = {
    "Размер": "gp_size", "Назначение": "gp_purpose", "Поверхность": "gp_surface", "Материал": "gp_material",
    "Применение": "gp_application", "Класс износостойкости (PEI)": "gp_pei", "Противоскользящая": "gp_antislip",
    "Ректификат": "gp_rectified", "Морозостойкость": "gp_frost", "Размер листа": "gp_sheet_size", "Основа": "gp_base",
    "Вес": "gp_weight", "Расход": "gp_consumption", "Класс клея": "gp_adhesive_class", "Цвет": "gp_color",
    "Ширина шва": "gp_joint", "Толщина слоя": "gp_layer", "Вид": "gp_kind", "Объём": "gp_volume",
    "Количество слоёв": "gp_layers", "Длина": "gp_length", "Ширина": "gp_width", "Степень блеска": "gp_sheen",
    "Класс стойкости к мокрому истиранию": "gp_wet_scrub", "Моющаяся": "gp_washable", "Для детских": "gp_kids",
    "Термостойкость": "gp_heat", "Ширина валика": "gp_roller_width", "Ширина рулона": "gp_roll_width",
    "Длина рулона": "gp_roll_length", "Раппорт": "gp_rapport", "Покрытие": "gp_coating", "Экологичность": "gp_eco",
    "Моющиеся": "gp_washable", "Влагостойкость": "gp_moisture", "Под покраску": "gp_paintable",
    "Площадь оклейки": "gp_coverage", "Класс износостойкости": "gp_wear_class", "Толщина": "gp_thickness",
    "Тип соединения": "gp_joint_type", "Декор": "gp_decor", "Порода": "gp_wood", "Ворс": "gp_pile",
    "Тип листа": "gp_sheet_type", "Толщина металла": "gp_metal", "Количество в упаковке": "gp_pack_qty",
    "Сечение": "gp_section", "Материал жил": "gp_core", "Площадь обогрева": "gp_heat_area", "Мощность": "gp_power",
    "Высота": "gp_height",
}

MARKETING = ["", "", "Хит продаж", "Выгодная цена", "Новинка сезона", "Профессиональная серия", "Российское производство"]
LABELS = [("sale", "Скидка"), ("hit", "Хит"), ("new", "Новинка"), ("eco", "Эко")]
WAREHOUSES = [(1, "Склад СПб, Парнас", 1), (2, "Склад СПб, Пулково", 1), (3, "Склад Москва, Север", 2)]
REGIONS = [
    {"id": 1, "code": "spb", "name": "Санкт-Петербург", "oracle_cod_city": 1, "priority": 0, "status": True,
     "is_default": True, "warehouses_count": 2},
    {"id": 2, "code": "msk", "name": "Москва", "oracle_cod_city": 2, "priority": 1, "status": True,
     "is_default": False, "warehouses_count": 1},
]


def ru(x):
    """Число в русском написании: 2.5 -> '2,5'."""
    if isinstance(x, float):
        s = f"{x:.3f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    return str(x)


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def fmt(tpl, params):
    out = tpl.format_map(SafeDict({k: ru(v) for k, v in params.items()}))
    return " ".join(out.split())


def package(spec, params, rng):
    """Возвращает (quantity_in_package, package_area, price_is_per_m2)."""
    kind = spec.get("pkg")
    if kind == "tile":
        w = params.get("w", 30) / 100
        h = params.get("h", params.get("w", 30)) / 100
        piece = w * h
        q = max(1, round(rng.choice([1.08, 1.2, 1.44, 1.5, 1.62]) / piece))
        return q, round(q * piece, 3), True
    if kind == "mosaic":
        return 1, 0.09, False
    if kind == "laminate":
        a = rng.choice([1.996, 2.131, 2.397, 1.67, 2.22])
        return rng.choice([7, 8, 9, 10]), a, True
    if kind == "underlay":
        return 1, float(params.get("a", 10)), True
    if kind == "insul":
        return rng.choice([6, 8, 12]), float(params.get("a", rng.choice([4.32, 5.5, 6]))), False
    if kind == "sheet":
        return 1, 3.0, False
    if kind == "heatmat":
        return 1, float(params.get("a", 2)), False
    if kind == "ceilpack":
        return 8, 2.0, False
    if kind == "ceilpanel":
        return 1, 0.75, False
    if kind == "wallpanel":
        return 1, 0.675, False
    return 1, None, False


def make_product(spec, pid, rng, cat_ids):
    params = {k: rng.choice(v) for k, v in spec["p"].items()}
    params.update({k: rng.choice(v) for k, v in spec.get("extra_p", {}).items()})
    brand = rng.choice(spec["brands"])
    params["brand"] = brand

    name = fmt(rng.choice(spec["names"]), params)
    if rng.random() < 0.12:
        name += f", арт. {rng.randint(10000, 99999)}"
    if rng.random() < 0.08:
        name = name.replace(brand, brand.upper())

    chars = []
    for cname, tpl in spec["chars"].items():
        chars.append({"code": CHAR_CODES.get(cname, "gp_other"), "name": cname, "value": fmt(tpl, params)})
    if spec["moist"] and not any(c["name"] == "Влагостойкость" for c in chars) and rng.random() < 0.6:
        chars.append({"code": "gp_moisture", "name": "Влагостойкость", "value": "да"})
    chars.append({"code": "gp_brand_country", "name": "Страна производства",
                  "value": rng.choice(["Россия", "Россия", "Беларусь", "Китай", "Турция", "Италия"])})
    # шум: часть характеристик в карточке отсутствует
    if len(chars) > 2 and rng.random() < 0.18:
        drop = rng.sample(range(len(chars)), k=rng.randint(1, min(2, len(chars) - 1)))
        chars = [c for i, c in enumerate(chars) if i not in drop]

    description = fmt(rng.choice(spec["desc"]), params) if spec["desc"] else ""

    q, parea, per_m2 = package(spec, params, rng)
    lo, hi = spec["price"]
    base = rng.uniform(lo, hi)
    if per_m2 and parea:
        price_per_m2 = round(base, 2)
        price = round(base * parea, 0)
    else:
        price = round(base, 0)
        price_per_m2 = round(price / parea, 2) if parea else None
    discount = 0.0
    special_active = rng.random() < 0.25
    if special_active:
        discount = round(price * rng.choice([0.05, 0.1, 0.15, 0.2]), 0)
    result_price = price - discount

    stocks = []
    for wid, wname, rid in WAREHOUSES:
        if rng.random() < 0.75:
            stocks.append({"warehouse_id": wid, "warehouse_name": wname, "region_id": rid, "qty": rng.randint(0, 240)})
    qty = sum(s["qty"] for s in stocks)
    labels = []
    if special_active:
        labels.append({"code": "sale", "name": "Скидка"})
    if rng.random() < 0.1:
        labels.append(dict(zip(("code", "name"), rng.choice(LABELS[1:]))))

    cat1, cat2 = spec["cat"]
    cid = cat_ids[(cat1, cat2)]
    pid_str = "".join(rng.choices(string.digits, k=7))
    url_key = f"/catalog/{spec['st'].replace('_', '-')}/{pid_str}/"
    return {
        "id": pid,
        "sku": f"MX-{rng.randint(100000, 999999)}",
        "cod_good": pid_str,
        "name": name,
        "marketing_description": rng.choice(MARKETING),
        "type": "simple",
        "url_key": url_key,
        "price": price,
        "result_price": result_price,
        "currency": "RUB",
        "quantity_in_package": q,
        "package_area": parea,
        "price_per_m2": price_per_m2 if price_per_m2 else None,
        "price_per_m2_unit": "₽/м2" if price_per_m2 else None,
        "discount_amount": discount,
        "discount_percent": round(discount / price * 100, 2) if price else 0,
        "special_price": result_price if special_active else None,
        "special_price_from": "2026-10-01 00:00:00" if special_active else None,
        "special_price_to": "2026-11-30 23:59:00" if special_active else None,
        "special_price_active": special_active,
        "old_price": price if special_active else None,
        "labels": labels,
        "qty": qty,
        "stocks": stocks,
        "in_stock": qty > 0,
        "status": True,
        "brand": {"id": zlib.crc32(brand.encode()) % 9000 + 10, "name": brand},
        "collection": {"id": zlib.crc32(params["coll"].encode()) % 9000 + 10, "name": params["coll"]} if params.get("coll") else None,
        "country": None,
        "categories": {str(cid): cat2},
        "categories_tree": [
            {"id": cat_ids[(cat1, None)], "name": cat1, "depth": 1},
            {"id": cid, "name": cat2, "depth": 2},
        ],
        "unit": spec["unit"],
        "matrix_type": 1,
        "matrix_type_name": "Обычный товар",
        "is_purchasable_online": True,
        "pickup_text": "Самовывоз сегодня" if qty > 0 else "Под заказ 3-5 дней",
        "ratings": {"rating": round(rng.uniform(3.6, 5.0), 1)} if rng.random() < 0.8 else {"rating": None},
        "recsys_rating": round(rng.lognormvariate(0, 0.6), 6),
        "propertiesBottom": [{"name": c["name"], "value": c["value"]} for c in chars[:3]],
        "created_at": f"2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)} 12:00:00",
        "description": description,
        "weight": None,
        "meta_title": name,
        "meta_description": description[:150],
        "updated_at": "2026-10-01 12:00:00",
        "characteristics": chars,
    }


def build_categories():
    cat_ids, children = {}, defaultdict(list)
    next_id = 2
    for spec in SUBTYPES:
        c1, c2 = spec["cat"]
        if (c1, None) not in cat_ids:
            cat_ids[(c1, None)] = next_id
            next_id += 1
        if (c1, c2) not in cat_ids:
            cat_ids[(c1, c2)] = next_id
            children[c1].append(c2)
            next_id += 1
    return cat_ids, children


def tree_json(cat_ids, children, counts):
    data = []
    for (c1, c2), cid in cat_ids.items():
        if c2 is not None:
            continue
        kids = []
        for name in children[c1]:
            kid = cat_ids[(c1, name)]
            kids.append({"id": kid, "parent_id": cid, "name": name, "url_key": f"cat-{kid}", "status": True,
                         "depth_level": 2, "product_count": counts.get(kid, 0),
                         "product_count_all_children": counts.get(kid, 0), "children": []})
        data.append({"id": cid, "parent_id": 1, "name": c1, "url_key": f"cat-{cid}", "status": True,
                     "depth_level": 1, "product_count": 0,
                     "product_count_all_children": sum(k["product_count"] for k in kids), "children": kids})
    return {"data": data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    cat_ids, children = build_categories()
    products, gold, new_products, new_gold = [], [], [], []
    pid = 96000
    for spec in SUBTYPES:
        n_new = max(1, math.ceil(spec["n"] * 0.1))
        for i in range(spec["n"] + n_new):
            pid += rng.randint(1, 9)
            p = make_product(spec, pid, rng, cat_ids)
            row = {"id": p["id"], "subtype": spec["st"], "kind": spec["kind"], "work_types": "|".join(spec["labels"])}
            if i < spec["n"]:
                products.append(p)
                gold.append(row)
            else:
                new_products.append(p)
                new_gold.append(row)

    counts = defaultdict(int)
    for p in products:
        counts[int(next(iter(p["categories"])))] += 1

    out = ROOT / "data" / "catalog"
    out.mkdir(parents=True, exist_ok=True)
    (out / "products.json").write_text(json.dumps(products, ensure_ascii=False, indent=1))
    (out / "new_products.json").write_text(json.dumps(new_products, ensure_ascii=False, indent=1))
    (out / "categories_tree.json").write_text(json.dumps(tree_json(cat_ids, children, counts), ensure_ascii=False, indent=1))
    (out / "regions.json").write_text(json.dumps({"data": REGIONS}, ensure_ascii=False, indent=1))

    gdir = ROOT / "data" / "gold"
    gdir.mkdir(parents=True, exist_ok=True)
    for fname, rows in (("labels.csv", gold), ("labels_new.csv", new_gold)):
        with open(gdir / fname, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "subtype", "kind", "work_types"], delimiter=";")
            w.writeheader()
            w.writerows(rows)

    multi = sum(1 for r in gold if r["work_types"].count("|") >= 1)
    empty = sum(1 for r in gold if not r["work_types"])
    print(f"products={len(products)} new={len(new_products)} subtypes={len(SUBTYPES)} "
          f"multi_label={multi} out_of_scope={empty} categories={len(cat_ids)}")


if __name__ == "__main__":
    main()
