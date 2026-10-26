"""Подбор и ранжирование товаров под позицию сметы с учётом специфики помещения.

1) кандидаты: товары, которые ML (или админка) отнёс к нужному виду работ и классу материала;
2) жёсткие ограничения помещения: влагостойкость для санузла, морозостойкость для балкона,
   класс износостойкости — если под ограничения ничего не нашлось, ограничение снимается с предупреждением;
3) ранжирование: уверенность ML, предпочтения позиции (ключевые слова), популярность (recsys_rating),
   рейтинг, наличие на складах региона, соответствие ценового сегмента типу ремонта.
"""
import math
import re

import numpy as np

PACKED_KINDS = {"paint", "primer", "tile_adhesive", "grout", "plaster_mix", "putty", "screed_mix", "self_leveling_mix",
                "waterproofing_mix", "decor_plaster"}
AREA_KINDS = {"tile", "laminate", "underlay", "insulation_board", "wall_panel", "ceiling_panel"}


def has_area(p: dict) -> bool:
    a = p["_attrs"]
    unit = (p.get("unit") or "").replace(".", "")
    return bool(p.get("package_area") or unit.startswith(("м²", "квм")) or
                (a.get("sheet_area_m2") and p.get("_kind") in ("wall_panel", "ceiling_panel", "insulation_board")))


PRICE_TARGET = {"cosmetic": 0.25, "capital": 0.5, "designer": 0.85}


def meets(p: dict, require: dict) -> bool:
    a = p["_attrs"]
    for k, v in require.items():
        if k == "wear_class_min":
            if a.get("wear_class") is not None and a["wear_class"] < v:
                return False
        elif v and not a.get(k):
            return False
    return True


def region_qty(p: dict, region_id: int | None) -> int | None:
    """Остаток в регионе; None — остатки неизвестны (в реальном каталоге есть только признак наличия из фида)."""
    stocks = p.get("stocks") or []
    if not stocks:
        return None if p.get("qty") is None else int(p["qty"])
    if region_id is None:
        return int(p.get("qty") or 0)
    return sum(int(s.get("qty") or 0) for s in stocks if s.get("region_id") == region_id)


def stock_score(p: dict, region_id: int | None) -> float:
    q = region_qty(p, region_id)
    if q is not None:
        return 1.0 if q > 0 else 0.0
    return {True: 1.0, False: 0.0}.get(p.get("in_stock"), 0.4)


def unit_price(p: dict) -> float:
    """Цена за единицу материала (м², кг, л), иначе за единицу продажи — чтобы сравнивать
    сегмент честно: мешок 25 кг не «дороже» банки 1,5 кг."""
    price = float(p.get("result_price") or 0)
    a = p.get("_attrs") or {}
    if p.get("price_per_m2"):
        return float(p["price_per_m2"])
    for key in ("weight_kg", "volume_l"):
        if a.get(key):
            return price / a[key]
    return price


def rank(cands: list[dict], work_type: str, prefer: list[str], repair: str, region_id: int | None,
         room_prof: dict | None = None) -> list[tuple[float, dict, dict]]:
    if not cands:
        return []
    prices = np.array([unit_price(p) for p in cands])
    order = prices.argsort().argsort()
    pct = order / max(len(cands) - 1, 1)
    target = PRICE_TARGET.get(repair, 0.5)
    rec = np.array([math.log1p(p.get("recsys_rating") or 0) for p in cands])
    rec = rec / rec.max() if rec.max() > 0 else rec
    out = []
    for i, p in enumerate(cands):
        name = (p["name"] + " " + (p.get("description") or "")).lower()
        ml = 1.0 if p.get("_source") == "manual" else p["_ml"]["proba"].get(work_type, 0.5)
        pref = sum(1 for w in prefer if w in name) / max(len(prefer), 1) if prefer else 0
        stock = stock_score(p, region_id)
        rating = ((p.get("ratings") or {}).get("rating") or 4.0) / 5
        price_fit = 1 - abs(pct[i] - target)
        bonus = 0.0
        if room_prof:
            a = p["_attrs"]
            if room_prof.get("eco") and a.get("kids_safe"):
                bonus += 0.1
            if room_prof.get("grease") and a.get("washable"):
                bonus += 0.1
        parts = {"ml": round(ml, 3), "prefer": round(pref, 3), "popularity": round(float(rec[i]), 3),
                 "rating": round(rating, 3), "in_stock": stock, "price_fit": round(float(price_fit), 3),
                 "room_bonus": bonus}
        score = 0.25 * ml + 0.25 * pref + 0.15 * rec[i] + 0.05 * rating + 0.15 * stock + 0.15 * price_fit + bonus
        out.append((float(score), p, parts))
    out.sort(key=lambda x: -x[0])
    return out


def pick(index, work_type: str, kind: str, prefer: list[str], require: dict, repair: str, region_id: int | None,
         room_prof: dict | None = None, must: str | None = None, optional: bool = False):
    cands = index.candidates(work_type, kind)
    warnings = []
    if must:
        matched = [p for p in cands if re.search(must, p["name"].lower())]
        if not matched and optional:
            return [], []
        if matched:
            cands = matched
        elif cands:
            warnings.append("точного товара для позиции нет в каталоге — показан ближайший по виду работ")
    if kind in AREA_KINDS:  # для расчёта по площади нужна известная фасовка
        known = [p for p in cands if has_area(p)]
        cands = known or cands
    elif kind in PACKED_KINDS:  # для смесей и ЛКМ нужен известный вес или объём упаковки
        known = [p for p in cands if p["_attrs"].get("weight_kg") or p["_attrs"].get("volume_l")]
        cands = known or cands
    ok = [p for p in cands if meets(p, require)]
    if require and not ok and cands:
        warnings.append(f"нет товаров, удовлетворяющих требованиям {require} — показаны ближайшие альтернативы")
        ok = cands
    return rank(ok, work_type, prefer, repair, region_id, room_prof), warnings
