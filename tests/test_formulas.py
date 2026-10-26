"""Эталонные расчёты, посчитанные вручную по нормам data/knowledge/norms.md.

Метрика кейса «точность расчёта расхода» = MAE по количеству относительно эталона; здесь она должна быть 0.
"""
import math

import pytest

from app.calc.formulas import compute
from app.calc.plan import Room
from app.catalog import attributes


def prod(name, chars=None, **kw):
    p = {"name": name, "characteristics": [{"name": k, "value": v} for k, v in (chars or {}).items()],
         "unit": "шт", **kw}
    return p, attributes(p)


# (описание, класс материала, база, товар, контекст, ожидаемое количество)
CASES = [
    ("плитка: стена 3,2×2,7 = 8,64 м², запас 10%, упаковка 1,08 м² → 9,5 / 1,08 = 8,8 → 9",
     "tile", 8.64, prod("Плитка настенная 20x60", {"Размер": "20x60 см"}, package_area=1.08, unit="упак."), {}, 9),
    ("ламинат: 15 м² × 1,07 = 16,05 / 2,131 = 7,53 → 8",
     "laminate", 15, prod("Ламинат 33 класс", package_area=2.131, unit="упак."), {}, 8),
    ("ламинат по диагонали: 15 × 1,15 = 17,25 / 2,131 = 8,09 → 9",
     "laminate", 15, prod("Ламинат 33 класс", package_area=2.131, unit="упак."), {"diagonal": True}, 9),
    ("обои: стены 13,2 м, рулон 1,06×10,05, раппорт 32 см: полоса 3,12 м, 3 полосы/рулон, 13 полос → 5 рулонов",
     "wallpaper", 30, prod("Обои флизелиновые", {"Ширина рулона": "1,06 м", "Длина рулона": "10,05 м", "Раппорт": "32 см"}),
     {"height": 2.7, "wall_length": 13.2}, 5),
    ("краска: 30 м² × 0,12 л × 2 слоя = 7,2 л / 2,5 л → 3",
     "paint", 30, prod("Краска интерьерная 2,5 л", {"Объём": "2,5 л", "Расход": "0,12 л/м² на 1 слой"}), {}, 3),
    ("плиточный клей: 10 м² × 4,5 кг = 45 кг / 25 → 2",
     "tile_adhesive", 10, prod("Клей для плитки 25 кг", {"Вес": "25 кг", "Расход": "4,5 кг/м² при толщине слоя 3 мм"}), {}, 2),
    ("гипсовая штукатурка: 20 м² × 0,85 кг/м²·мм × 15 мм = 255 кг / 30 → 9",
     "plaster_mix", 20, prod("Штукатурка гипсовая 30 кг", {"Вес": "30 кг", "Расход": "8,5 кг/м² при толщине слоя 10 мм"}), {}, 9),
    ("стяжка: 10 м² × 2 кг/м²·мм × 40 мм = 800 кг / 50 → 16",
     "screed_mix", 10, prod("Пескобетон М300 50 кг", {"Вес": "50 кг", "Расход": "20 кг/м² при толщине слоя 10 мм"}), {}, 16),
    ("наливной пол: 12 м² × 1,6 × 5 мм = 96 кг / 25 → 4",
     "self_leveling_mix", 12, prod("Наливной пол 25 кг", {"Вес": "25 кг", "Расход": "1,6 кг/м² при толщине слоя 1 мм"}), {}, 4),
    ("финишная шпаклёвка: 40 м² × 1 кг × 1 мм = 40 кг / 20 → 2",
     "putty", 40, prod("Шпаклёвка финишная 20 кг", {"Вес": "20 кг", "Расход": "1 кг/м² при толщине слоя 1 мм"}), {}, 2),
    ("линолеум: комната 3,4×4,5, рулон 3,5 м → 1 полоса × 3,5 × 4,6 = 16,1 м²",
     "linoleum", 15.3, prod("Линолеум бытовой", {"Ширина рулона": "3,5 м"}, unit="м²"), {"length": 4.5, "width": 3.4}, 16.1),
    ("плинтус: 13,2 м × 1,05 = 13,86 / 2,5 → 6",
     "skirting", 13.2, prod("Плинтус ПВХ 2,5 м", {"Длина": "2,5 м"}), {}, 6),
    ("гидроизоляция: 8,94 м² × 1,2 кг × 2 слоя = 21,46 кг / 15 → 2",
     "waterproofing_mix", 8.94, prod("Гидроизоляция 15 кг", {"Вес": "15 кг", "Расход": "1,2 кг/м² на слой"}), {}, 2),
    ("тёплый пол: 6 м² × 0,7 = 4,2 / 2 м² → 3",
     "heating_mat", 6, prod("Мат нагревательный 2 м²", {"Площадь обогрева": "2 м²"}), {}, 3),
    ("ГКЛ: 20 м² × 1,1 / 3 м² → 8",
     "drywall_sheet", 20, prod("ГКЛВ 12,5 мм", package_area=3.0), {}, 8),
    ("обойный клей: 45 м² / 30 м² → 2",
     "wallpaper_glue", 45, prod("Клей для обоев", {"Площадь оклейки": "до 30 м²"}), {}, 2),
]


@pytest.mark.parametrize("title,kind,basis,pa,ctx,expected", CASES, ids=[c[0][:40] for c in CASES])
def test_reference_estimates(title, kind, basis, pa, ctx, expected):
    p, a = pa
    need = compute(kind, basis, a, p, ctx)
    assert need.qty == pytest.approx(expected, abs=0.01), f"{title}: {need.formula}"


def test_mae_on_reference_set_is_zero():
    errors = [abs(compute(k, b, a, p, c).qty - e) for _, k, b, (p, a), c, e in CASES]
    assert sum(errors) / len(errors) < 0.01


def test_room_geometry_square_bathroom():
    r = Room(type="bathroom", area=6)
    assert r.perimeter == pytest.approx(4 * math.sqrt(6))
    assert r.wall_area == pytest.approx(r.perimeter * 2.7 - 0.8 * 2.0, abs=0.01)
    assert r.windows == 0


def test_defaults_when_characteristics_missing():
    p, a = prod("Клей для плитки без характеристик 25 кг")
    need = compute("tile_adhesive", 10, a, p, {})
    assert need.qty == 2 and any("по умолчанию" in x for x in need.assumptions)


def test_attributes_parsing():
    _, a = prod("Гипсокартон влагостойкий ГКЛВ 12,5x1200x2500 мм")
    assert a["moisture_resistant"]
    _, a = prod("Краска моющаяся для кухонь 2,7 л")
    assert a["washable"] and a["volume_l"] == 2.7
    _, a = prod("Шпаклёвка финишная 20 кг", {"Расход": "1 кг/м² при толщине слоя 1 мм"})
    assert a["weight_kg"] == 20 and a["consumption"]["per_mm"] == 1.0
