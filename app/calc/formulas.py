"""Нормативные формулы расхода материалов.

Каждая функция получает базу расчёта (площадь, длину или количество) и нормализованные признаки
товара (app.catalog.attributes) и возвращает Need: сколько единиц продажи купить и как это посчитано.
Если в карточке нет нужной характеристики, используется типовая норма из DEFAULTS
(источник — data/knowledge/norms.md), и это явно отмечается в пояснении.
"""
import math
from dataclasses import dataclass, field

# Типовые нормы, если в карточке нет характеристики (см. data/knowledge/norms.md)
DEFAULTS = {
    "tile_waste": 0.10, "tile_waste_diagonal": 0.15, "tile_waste_small_room": 0.05,
    "tile_adhesive_kg_m2": 4.5, "grout_kg_m2": 0.5, "primer_l_m2": 0.15,
    "paint_l_m2_layer": 0.12, "paint_layers": 2, "paint_density_kg_l": 1.4,
    "wallpaper_glue_m2_per_pack": 30, "wallpaper_strip_reserve_m": 0.1,
    "plaster_kg_m2_mm": 0.85, "plaster_mm": 15, "plaster_cement_kg_m2_mm": 1.5,
    "putty_kg_m2_mm": 1.0, "putty_start_mm": 3, "putty_finish_mm": 1,
    "screed_kg_m2_mm": 2.0, "screed_mm": 40, "self_leveling_kg_m2_mm": 1.6, "self_leveling_mm": 5,
    "wp_kg_m2_layer": 1.2, "wp_layers": 2, "wp_wall_rise_m": 0.3,
    "laminate_waste": 0.07, "laminate_waste_diagonal": 0.15, "underlay_waste": 0.05, "linoleum_trim_m": 0.1,
    "skirting_piece_m": 2.5, "skirting_reserve": 0.05,
    "drywall_sheet_m2": 3.0, "drywall_waste": 0.10, "profile_m_per_m2": 2.0, "profile_piece_m": 3.0,
    "screws_per_m2": 30, "hangers_per_m2": 1.7,
    "insulation_waste": 0.05, "panel_waste": 0.10,
    "cable_m_per_point": 7.0, "cable_reserve_m": 10.0, "conduit_piece_m": 50.0,
    "warm_floor_share": 0.7, "wp_tape_roll_m": 10.0, "damper_roll_m": 25.0, "beacon_step_m": 1.5,
    "decor_kg_m2": 1.0, "molding_piece_m": 2.0,
}


@dataclass
class Need:
    qty: float  # единицы продажи (упаковки, штуки, м², м)
    amount: str = ""  # физическое количество материала, например «38,5 кг»
    formula: str = ""
    assumptions: list = field(default_factory=list)


def ru(x: float, nd=2) -> str:
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _packs(total: float, per_pack: float | None, unit: str, label: str, default_note: list) -> Need:
    if not per_pack:
        return Need(qty=math.ceil(total), amount=f"{ru(total)} {unit}",
                    formula=f"фасовка не указана в карточке — {label}", assumptions=default_note)
    q = math.ceil(total / per_pack - 1e-9)
    return Need(qty=q, amount=f"{ru(total)} {unit}",
                formula=f"{ru(total)} {unit} / {ru(per_pack)} {unit} в упаковке = {ru(total / per_pack)} → {q}",
                assumptions=default_note)


# Правдоподобные диапазоны норм: значение из карточки вне диапазона пробуем перевести
# (г -> кг, «м² на литр» -> л/м²), иначе берём типовую норму. В каталоге расход часто указан без единиц.
PLAUSIBLE = {
    "tile_adhesive_kg_m2": (1.5, 9), "grout_kg_m2": (0.1, 2), "primer_l_m2": (0.04, 0.5),
    "paint_l_m2_layer": (0.05, 0.35), "plaster_kg_m2_mm": (0.5, 2), "plaster_cement_kg_m2_mm": (0.8, 2.2),
    "putty_kg_m2_mm": (0.4, 2), "screed_kg_m2_mm": (1.4, 2.5), "self_leveling_kg_m2_mm": (1.1, 2.1),
    "wp_kg_m2_layer": (0.3, 3), "decor_kg_m2": (0.1, 4),
}


def consumption(a, default_key, per_mm=False):
    c = a.get("consumption")
    lo, hi = PLAUSIBLE.get(default_key, (0, 1e9))
    if c:
        if per_mm and c.get("per_mm"):
            return c["per_mm"], []
        v = c["value"]
        if v and not (per_mm and c.get("layer_mm")):
            for cand, note in ((v, ""), (v / 1000, " (переведено из г)"), (1 / v, " (из «м² на единицу»)")):
                if lo <= cand <= hi:
                    return cand, [f"расход из карточки: {c.get('raw', ru(v))}{note}"] if note else []
    return DEFAULTS[default_key], [f"норма расхода по умолчанию: {ru(DEFAULTS[default_key])}"]


# ---------- формулы по классу материала ----------

def area_material(area, a, p, waste, waste_note):
    """Плитка, ламинат, подложка, панели: площадь с запасом / площадь упаковки."""
    need = area * (1 + waste)
    parea = p.get("package_area")
    unit = (p.get("unit") or "").replace(".", "")
    if unit.startswith("м²") or unit.startswith("квм") or (not parea and p.get("price_per_m2")):
        return Need(qty=round(need, 2), amount=f"{ru(need)} м²", formula=f"{ru(area)} м² × (1 + {ru(waste)}) = {ru(need)} м²",
                    assumptions=[waste_note])
    if not parea:
        return Need(qty=math.ceil(need), amount=f"{ru(need)} м²",
                    formula="площадь упаковки не указана — 1 шт на 1 м²", assumptions=[waste_note])
    q = math.ceil(need / parea - 1e-9)
    return Need(qty=q, amount=f"{ru(need)} м²",
                formula=f"{ru(area)} м² × (1 + {ru(waste)}) = {ru(need)} м² / {ru(parea, 3)} м² в упаковке → {q}",
                assumptions=[waste_note])


def tile(area, a, p, ctx):
    waste = DEFAULTS["tile_waste_diagonal"] if ctx.get("diagonal") else DEFAULTS["tile_waste"]
    note = f"запас на подрезку {int(waste * 100)}%"
    if area < 4:
        waste += DEFAULTS["tile_waste_small_room"]
        note += " + 5% (малая площадь)"
    return area_material(area, a, p, waste, note)


def mosaic(area, a, p, ctx):
    need = area * 1.1
    q = math.ceil(need / 0.09)
    return Need(q, f"{ru(need)} м²", f"{ru(need)} м² / 0,09 м² (лист 30×30) → {q}", ["запас 10%"])


def by_weight(kg, a, label, notes):
    return _packs(kg, a.get("weight_kg"), "кг", label, notes)


def tile_adhesive(area, a, p, ctx):
    c0 = (a.get("consumption") or {}).get("value")
    if c0 and 0.8 <= c0 < 1.5:  # в карточке расход на 1 мм слоя -> слой 3 мм
        c, n = c0 * 3, [f"расход из карточки {ru(c0)} кг/м² на 1 мм × слой 3 мм"]
    else:
        c, n = consumption(a, "tile_adhesive_kg_m2")
    return by_weight(area * c, a, f"{ru(area)} м² × {ru(c)} кг/м²", n)


def grout(area, a, p, ctx):
    c, n = consumption(a, "grout_kg_m2")
    return by_weight(area * c, a, f"{ru(area)} м² × {ru(c)} кг/м²", n)


def by_volume_or_weight(total_l, a, label, notes):
    if a.get("volume_l"):
        return _packs(total_l, a["volume_l"], "л", label, notes)
    return by_weight(total_l, a, label, notes)


def primer(area, a, p, ctx):
    c, n = consumption(a, "primer_l_m2")
    coats = ctx.get("primer_coats", 1)
    return by_volume_or_weight(area * c * coats, a, f"{ru(area)} м² × {ru(c)} × {coats} сл.", n)


def paint(area, a, p, ctx):
    c, n = consumption(a, "paint_l_m2_layer")
    layers = ctx.get("layers", DEFAULTS["paint_layers"])
    liters = area * c * layers
    if not a.get("volume_l") and a.get("weight_kg"):  # краска продаётся в кг: плотность в/д краски ≈ 1,4 кг/л
        kg = liters * DEFAULTS["paint_density_kg_l"]
        need = _packs(kg, a["weight_kg"], "кг", "", n + [f"{layers} слоя", "плотность краски 1,4 кг/л"])
        need.formula = (f"{ru(area)} м² × {ru(c)} л/м² × {layers} сл. = {ru(liters)} л × 1,4 кг/л = {ru(kg)} кг "
                        f"/ {ru(a['weight_kg'])} кг → {need.qty} шт")
        return need
    need = _packs(liters, a.get("volume_l"), "л", "", n + [f"{layers} слоя"])
    need.formula = f"{ru(area)} м² × {ru(c)} л/м² × {layers} сл. = {ru(liters)} л → {need.qty} шт"
    return need


def wallpaper(area, a, p, ctx):
    h = ctx.get("height", 2.7)
    perim = ctx.get("wall_length") or area / h
    w = a.get("roll_width_m") or 1.06
    L = a.get("roll_length_m") or 10.05
    rap = a.get("rapport_m") or 0
    strip = h + rap + DEFAULTS["wallpaper_strip_reserve_m"]
    per_roll = max(1, math.floor(L / strip))
    strips = math.ceil(perim / w)
    q = math.ceil(strips / per_roll)
    notes = [] if a.get("roll_width_m") else ["размер рулона по умолчанию 1,06×10,05 м"]
    return Need(q, f"{strips} полос",
                f"полос: {ru(perim)} м / {ru(w)} м = {strips}; полос в рулоне: ⌊{ru(L)} / ({ru(h)} + раппорт {ru(rap)} + 0,1)⌋ = {per_roll} → {q} рулонов",
                notes)


def wallpaper_glue(area, a, p, ctx):
    c = (a.get("consumption") or {}).get("value")
    cov = a.get("coverage_m2") or (c if c and 5 <= c <= 200 else None) or DEFAULTS["wallpaper_glue_m2_per_pack"]
    q = math.ceil(area / cov)
    return Need(q, f"{ru(area)} м²", f"{ru(area)} м² / {ru(cov)} м² на пачку → {q}",
                [] if cov != DEFAULTS["wallpaper_glue_m2_per_pack"] else ["30 м² на пачку по умолчанию"])


def plaster_mix(area, a, p, ctx):
    cement = "цемент" in p.get("name", "").lower()
    c, n = consumption(a, "plaster_cement_kg_m2_mm" if cement else "plaster_kg_m2_mm", per_mm=True)
    mm = ctx.get("plaster_mm", DEFAULTS["plaster_mm"])
    need = by_weight(area * c * mm, a, "", n + [f"средняя толщина слоя {mm} мм"])
    need.formula = f"{ru(area)} м² × {ru(c)} кг/м²·мм × {mm} мм = {ru(area * c * mm)} кг; " + need.formula
    return need


def putty(area, a, p, ctx):
    c, n = consumption(a, "putty_kg_m2_mm", per_mm=True)
    finish = "финиш" in p.get("name", "").lower() or ctx.get("putty_layer") == "finish"
    mm = DEFAULTS["putty_finish_mm"] if finish else DEFAULTS["putty_start_mm"]
    need = by_weight(area * c * mm, a, "", n + [f"толщина слоя {mm} мм"])
    need.formula = f"{ru(area)} м² × {ru(c)} кг/м²·мм × {mm} мм = {ru(area * c * mm)} кг; " + need.formula
    return need


def screed_mix(area, a, p, ctx):
    c, n = consumption(a, "screed_kg_m2_mm", per_mm=True)
    mm = ctx.get("screed_mm", DEFAULTS["screed_mm"])
    need = by_weight(area * c * mm, a, "", n + [f"толщина стяжки {mm} мм"])
    need.formula = f"{ru(area)} м² × {ru(c)} кг/м²·мм × {mm} мм = {ru(area * c * mm)} кг; " + need.formula
    return need


def self_leveling_mix(area, a, p, ctx):
    c, n = consumption(a, "self_leveling_kg_m2_mm", per_mm=True)
    mm = ctx.get("self_leveling_mm", DEFAULTS["self_leveling_mm"])
    need = by_weight(area * c * mm, a, "", n + [f"толщина слоя {mm} мм"])
    need.formula = f"{ru(area)} м² × {ru(c)} кг/м²·мм × {mm} мм = {ru(area * c * mm)} кг; " + need.formula
    return need


def waterproofing_mix(area, a, p, ctx):
    c, n = consumption(a, "wp_kg_m2_layer")
    layers = DEFAULTS["wp_layers"]
    need = by_weight(area * c * layers, a, "", n + [f"{layers} слоя", "заведение на стены 30 см"])
    need.formula = f"{ru(area)} м² × {ru(c)} кг/м² × {layers} сл. = {ru(area * c * layers)} кг; " + need.formula
    return need


def per_length(length, piece, label):
    q = math.ceil(length / piece - 1e-9)
    return Need(q, f"{ru(length)} м", f"{ru(length)} м / {ru(piece)} м → {q} шт", [label] if label else [])


def waterproofing_tape(length, a, p, ctx):
    return per_length(length, a.get("length_m") or DEFAULTS["wp_tape_roll_m"], "")


def laminate(area, a, p, ctx):
    waste = DEFAULTS["laminate_waste_diagonal"] if ctx.get("diagonal") else DEFAULTS["laminate_waste"]
    return area_material(area, a, p, waste, f"запас на подрезку {int(waste * 100)}%")


def underlay(area, a, p, ctx):
    return area_material(area, a, p, DEFAULTS["underlay_waste"], "запас 5%")


def linoleum(area, a, p, ctx):
    w = a.get("roll_width_m")
    L, W = ctx.get("length"), ctx.get("width")
    trim = DEFAULTS["linoleum_trim_m"]
    if w and L and W:
        short, long_ = sorted((L, W))
        strips = math.ceil(short / w - 1e-9)
        need = strips * w * (long_ + trim)
        f = f"{strips} полос(а) × {ru(w)} м × ({ru(long_)} + {ru(trim)}) м = {ru(need)} м²"
    else:
        need = area * 1.1
        f = f"{ru(area)} м² × 1,1 = {ru(need)} м² (размеры комнаты не заданы)"
    return Need(round(need, 2), f"{ru(need)} м²", f, ["подрезка по краям 10 см"])


def skirting(length, a, p, ctx):
    piece = a.get("length_m") or DEFAULTS["skirting_piece_m"]
    L = length * (1 + DEFAULTS["skirting_reserve"])
    return per_length(L, piece, "запас 5%, за вычетом дверных проёмов")


def skirting_accessory(count, a, p, ctx):
    return Need(math.ceil(count), f"{math.ceil(count)} шт", "4 угла + 2 заглушки на дверной проём")


def drywall_sheet(area, a, p, ctx):
    sheet = p.get("package_area") or a.get("sheet_area_m2") or DEFAULTS["drywall_sheet_m2"]
    need = area * (1 + DEFAULTS["drywall_waste"])
    q = math.ceil(need / sheet)
    return Need(q, f"{ru(need)} м²", f"{ru(area)} м² × 1,1 / {ru(sheet)} м² лист → {q}", ["запас 10%"])


def profile(area, a, p, ctx):
    m = area * DEFAULTS["profile_m_per_m2"]
    return per_length(m, a.get("length_m") or DEFAULTS["profile_piece_m"], "≈2 п.м профиля на 1 м² обшивки")


def fastener(area, a, p, ctx):
    name = p.get("name", "").lower()
    per_m2 = DEFAULTS["hangers_per_m2"] if ("подвес" in name or "краб" in name) else DEFAULTS["screws_per_m2"]
    n = area * per_m2
    pack = a.get("pack_qty")
    q = math.ceil(n / pack) if pack else 1
    return Need(q, f"{math.ceil(n)} шт", f"{ru(area)} м² × {ru(per_m2)} шт/м² = {math.ceil(n)} шт" + (f" / {int(pack)} в упаковке → {q}" if pack else ""))


def _with_sheet_area(a, p, per_pack=False):
    """Площадь упаковки из размеров листа (мм) × штук в упаковке, если в карточке нет готовой площади."""
    if p.get("package_area") or not a.get("sheet_area_m2"):
        return p
    q = (a.get("pack_qty") or 1) if per_pack else 1
    return {**p, "package_area": round(a["sheet_area_m2"] * q, 3)}


def insulation_board(area, a, p, ctx):
    return area_material(area, a, _with_sheet_area(a, p, per_pack=True), DEFAULTS["insulation_waste"], "запас 5%")


def panel(area, a, p, ctx):
    unit = (p.get("unit") or "").replace(".", "")
    return area_material(area, a, _with_sheet_area(a, p, per_pack=unit.startswith("уп")), DEFAULTS["panel_waste"],
                         "запас 10%")


def cable(points, a, p, ctx):
    m = points * DEFAULTS["cable_m_per_point"] + DEFAULTS["cable_reserve_m"]
    unit = (p.get("unit") or "").replace(".", "")
    pack = a.get("cable_pack_m") or (a.get("length_m") if (a.get("length_m") or 0) >= 5 else None)
    if pack and not unit.startswith(("м", "пм")):  # продаётся бухтами
        q = math.ceil(m / pack - 1e-9)
        return Need(q, f"{round(m)} м", f"{int(points)} точек × 7 м + 10 м = {round(m)} м / бухта {ru(pack)} м → {q}")
    return Need(round(m), f"{round(m)} м", f"{int(points)} точек × 7 м + 10 м запас = {round(m)} м")


def conduit(points, a, p, ctx):
    m = points * DEFAULTS["cable_m_per_point"] + DEFAULTS["cable_reserve_m"]
    piece = a.get("length_m") or DEFAULTS["conduit_piece_m"]
    return per_length(m, piece, "длина равна длине кабеля")


def heating_mat(area, a, p, ctx):
    need = area * DEFAULTS["warm_floor_share"]
    per = a.get("coverage_m2") or p.get("package_area") or 2
    q = math.ceil(need / per - 1e-9)
    return Need(q, f"{ru(need)} м²", f"{ru(area)} м² × 0,7 (без зоны сантехники) = {ru(need)} м² / {ru(per)} м² → {q}",
                ["70% площади пола свободно от сантехники и мебели"])


def decor_plaster(area, a, p, ctx):
    c, n = consumption(a, "decor_kg_m2")
    return by_weight(area * c, a, "", n)


def molding(length, a, p, ctx):
    return per_length(length, a.get("length_m") or DEFAULTS["molding_piece_m"], "")


def count(n, a, p, ctx):
    n = math.ceil(n)
    return Need(n, f"{n} шт", f"{n} шт")


def one(n, a, p, ctx):
    return Need(1, "1 шт", "1 шт на объект")


FORMULAS = {
    "tile": tile, "mosaic": mosaic, "tile_adhesive": tile_adhesive, "grout": grout, "primer": primer, "paint": paint,
    "wallpaper": wallpaper, "wallpaper_glue": wallpaper_glue, "plaster_mix": plaster_mix, "putty": putty,
    "screed_mix": screed_mix, "self_leveling_mix": self_leveling_mix, "waterproofing_mix": waterproofing_mix,
    "waterproofing_tape": waterproofing_tape, "laminate": laminate, "underlay": underlay, "linoleum": linoleum,
    "skirting": skirting, "skirting_accessory": skirting_accessory, "drywall_sheet": drywall_sheet,
    "profile": profile, "fastener": fastener, "insulation_board": insulation_board, "wall_panel": panel,
    "ceiling_panel": panel, "cable": cable, "conduit": conduit, "heating_mat": heating_mat,
    "decor_plaster": decor_plaster, "molding": molding,
    "electro_box": count, "socket": count, "switch": count, "light": count, "electro_breaker": count,
    "plumbing_fixture": count, "pipe": count, "thermostat": count, "fan": count, "vent_part": count,
    "door": count, "door_part": count, "window_sill": count, "sealant": count, "foam": count, "radiator": count,
    "consumable": count, "tool": one, "accessory": count,
}

# Какая база расчёта нужна классу материала (для эндпоинта карточки товара)
BASIS = {
    "area": {"tile", "mosaic", "tile_adhesive", "grout", "primer", "paint", "wallpaper", "wallpaper_glue",
             "plaster_mix", "putty", "screed_mix", "self_leveling_mix", "waterproofing_mix", "laminate", "underlay",
             "linoleum", "drywall_sheet", "profile", "fastener", "insulation_board", "wall_panel", "ceiling_panel",
             "heating_mat", "decor_plaster"},
    "length": {"skirting", "waterproofing_tape", "molding"},
    "points": {"cable", "conduit"},
}


def compute(kind: str, basis: float, a: dict, p: dict, ctx: dict | None = None) -> Need:
    fn = FORMULAS.get(kind, count)
    return fn(basis, a, p, ctx or {})
