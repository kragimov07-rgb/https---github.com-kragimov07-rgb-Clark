"""Сборка сметы: план работ по помещениям -> подбор товаров -> расчёт количества -> стоимость (Decimal)."""
import time
from decimal import ROUND_HALF_UP, Decimal

from ..recommend import pick, region_qty
from ..taxonomy import rooms as taxonomy_rooms
from ..taxonomy import taxonomy, work_type_name
from .formulas import compute
from .plan import Room, plan_room, room_profile

CENT = Decimal("0.01")
OBJECT_COEF = {"apartment": 1.0, "studio": 1.0, "house": 1.0}


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def product_brief(p: dict) -> dict:
    return {"id": p["id"], "sku": p.get("sku"), "name": p["name"], "url_key": p.get("url_key"),
            "unit": p.get("unit"), "result_price": p.get("result_price"), "price": p.get("price"),
            "package_area": p.get("package_area"), "in_stock": p.get("in_stock"),
            "rating": (p.get("ratings") or {}).get("rating"), "source": p.get("_source")}


def line_for(index, slot, repair, region_id, prof, alternatives=2):
    ranked, warns = pick(index, slot.work_type, slot.kind, slot.prefer, slot.require, repair, region_id, prof)
    if not ranked:
        return None, [f"в каталоге нет товаров для «{slot.title}» ({slot.work_type}/{slot.kind})"]
    # оптимизация фасовки: среди близких по рангу товаров берём минимальную итоговую стоимость
    top = ranked[0][0]
    close = [r for r in ranked[:6] if r[0] >= top - 0.08]
    costed = []
    for s, q, parts_q in close:
        n = compute(slot.kind, slot.basis, q["_attrs"], q, slot.ctx)
        costed.append((money(Decimal(str(n.qty)) * money(q.get("result_price") or 0)), s, q, parts_q, n))
    cost, score, p, parts, need = min(costed, key=lambda x: (x[0], -x[1]))
    if p is not ranked[0][1]:
        ranked = [r for r in ranked if r[1] is p] + [r for r in ranked if r[1] is not p]
    price = money(p.get("result_price") or 0)
    stock = region_qty(p, region_id)
    if p.get("in_stock") is False:
        warns.append("товара нет в наличии по данным фида")
    elif stock is not None and stock < need.qty:
        warns.append(f"на складах региона {stock} {p.get('unit')}, нужно {need.qty}")
    alts = []
    for s, q, _ in ranked[1:1 + alternatives]:
        n2 = compute(slot.kind, slot.basis, q["_attrs"], q, slot.ctx)
        alts.append({**product_brief(q), "qty": n2.qty, "cost": str(money(Decimal(str(n2.qty)) * money(q.get("result_price") or 0)))})
    return {
        "title": slot.title, "work_type": slot.work_type, "work_type_name": work_type_name(slot.work_type),
        "kind": slot.kind, "surface": slot.surface, "basis": slot.basis, "optional": slot.optional,
        "product": product_brief(p), "qty": need.qty, "unit": p.get("unit"), "amount": need.amount,
        "formula": need.formula, "assumptions": need.assumptions, "unit_price": str(price), "cost": str(cost),
        "score": round(score, 3), "score_parts": parts, "requirements": slot.require, "alternatives": alts,
        "warnings": warns,
    }, []


def estimate(index, object_type: str, repair_type: str, rooms: list[dict], region_id: int | None = 1,
             include_optional: bool = True) -> dict:
    t0 = time.perf_counter()
    tx_rooms = taxonomy_rooms()
    result_rooms, total, by_wt, warnings = [], Decimal(0), {}, []
    tools: dict[int, dict] = {}
    for i, r in enumerate(rooms):
        room = Room(**r)
        prof = room_profile(room, tx_rooms)
        lines = []
        for slot in plan_room(room, object_type, repair_type, prof):
            if slot.optional and not include_optional:
                continue
            line, w = line_for(index, slot, repair_type, region_id, prof)
            warnings += [f"{room.name or tx_rooms.get(room.type, {}).get('name', room.type)}: {x}" for x in w]
            if not line:
                continue
            if slot.kind == "tool":  # инструмент покупается один раз на весь объект
                pid = line["product"]["id"]
                if pid in tools:
                    continue
                tools[pid] = line
            lines.append(line)
        room_total = sum((Decimal(l["cost"]) for l in lines), Decimal(0))
        for l in lines:
            by_wt[l["work_type"]] = by_wt.get(l["work_type"], Decimal(0)) + Decimal(l["cost"])
        total += room_total
        result_rooms.append({
            "index": i, "type": room.type, "name": room.name or tx_rooms.get(room.type, {}).get("name", room.type),
            "geometry": {"floor_m2": round(room.area, 2), "perimeter_m": round(room.perimeter, 2),
                         "walls_m2": round(room.wall_area, 2), "height_m": room.height,
                         "doors": room.doors, "windows": room.windows},
            "profile": prof, "lines": lines, "total": str(money(room_total)),
        })
    tx = taxonomy()
    return {
        "object_type": object_type, "object_type_name": tx["object_types"].get(object_type, object_type),
        "repair_type": repair_type, "repair_type_name": tx["repair_types"].get(repair_type, repair_type),
        "region_id": region_id, "rooms": result_rooms, "total": str(money(total)), "currency": "RUB",
        "by_work_type": [{"id": k, "name": work_type_name(k), "cost": str(money(v))}
                         for k, v in sorted(by_wt.items(), key=lambda x: -x[1])],
        "lines_count": sum(len(r["lines"]) for r in result_rooms),
        "warnings": warnings, "elapsed_ms": round(1000 * (time.perf_counter() - t0), 1),
        "disclaimer": "Расчёт ориентировочный: стоимость материалов по ценам каталога без учёта работ и доставки.",
    }
