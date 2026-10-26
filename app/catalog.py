"""Каталог товаров: загрузка в формате API стенда, нормализация характеристик, извлечение признаков."""
import json
import re
from pathlib import Path

from .config import CATALOG_PATH

NUM = r"((?:\d+(?:[.,]\d+)?)|(?:(?<!\d)[.,]\d+))"  # «2,5», «10», «.9» (так бывает в каталоге)


def to_float(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(NUM, str(s))
    return float("0" + m.group(1).replace(",", ".") if m.group(1)[0] in ".," else m.group(1).replace(",", ".")) if m else None


def char_map(p: dict) -> dict[str, str]:
    """Характеристики карточки: name -> value (исходный текст сохраняется)."""
    out = {}
    for c in p.get("characteristics") or []:
        out[c["name"]] = str(c.get("value", ""))
    for c in p.get("propertiesBottom") or []:
        out.setdefault(c["name"], str(c.get("value", "")))
    return out


def category_path(p: dict) -> list[str]:
    tree = p.get("categories_tree") or []
    if tree:
        return [c["name"] for c in sorted(tree, key=lambda c: c.get("depth", 0))]
    return list((p.get("categories") or {}).values())


def product_text(p: dict) -> str:
    """Текст товара для ML: название, путь в каталоге, описания и характеристики."""
    chars = "; ".join(f"{k}: {v}" for k, v in char_map(p).items())
    parts = [
        p.get("name", ""),
        " / ".join(category_path(p)),
        p.get("description") or "",
        p.get("marketing_description") or "",
        chars,
    ]
    return ". ".join(x for x in parts if x)


def _range_mean(value: str) -> float | None:
    """'2,1-5,2' -> 3.65; '0,1–0,2 л/м²' -> 0.15; '25' -> 25."""
    nums = [float(x.replace(",", ".")) for x in re.findall(NUM, value or "")]
    if not nums:
        return None
    if len(nums) >= 2 and re.search(NUM + r"\s*[-–—]\s*" + NUM, value):
        return (nums[0] + nums[1]) / 2
    return nums[0]


def parse_consumption(value: str) -> dict | None:
    """Расход: '8,5 кг/м² при толщине слоя 10 мм' -> {'value': 8.5, 'unit': 'кг', 'per_mm': 0.85};
    '2,1-5,2' (без единиц, как в каталоге) -> {'value': 3.65, 'unit': None}."""
    if not value:
        return None
    m = re.search(NUM + r"(?:\s*[-–—]\s*" + NUM + r")?\s*(кг|л|г)\s*/\s*м", value)
    if m:
        a = float(m.group(1).replace(",", "."))
        b = float(m.group(2).replace(",", ".")) if m.group(2) else a
        out = {"value": (a + b) / 2, "unit": m.group(3)}
    else:
        v = _range_mean(value)
        if v is None:
            return None
        out = {"value": v, "unit": None}
    layer = re.search(r"сло[яеи][^\d]*" + NUM + r"\s*мм", value)
    if layer:
        mm = float(layer.group(1).replace(",", "."))
        out["layer_mm"] = mm
        out["per_mm"] = out["value"] / mm if mm else None
    if re.search(r"на\s*(1\s*)?слой", value):
        out["per_layer"] = True
    out["raw"] = value
    return out


def _find(pattern: str, text: str) -> float | None:
    m = re.search(NUM + r"\s*" + pattern, text)
    return float(m.group(1).replace(",", ".")) if m else None


YES = re.compile(r"^\s*(да|есть|yes)\b", re.I)
NO = re.compile(r"^\s*(нет|no)\b|^\s*не\s", re.I)
MOIST_WORDS = re.compile(r"(?<!не )(?<!не)влагостойк|гклв|водостойк|влагозащищ|ip\s?(4[4-9]|5\d|6\d)|для ванн|"
                         r"влажных помещ|повышенной влажност|душев|бассейн|ванная", re.I)


def _flag(ch: dict, names: list[str], text: str, words: re.Pattern) -> bool:
    for n in names:
        v = ch.get(n)
        if v is None:
            continue
        if NO.search(v) or re.search(r"\bне\s+\w*" + words.pattern.split("|")[0][-8:], v, re.I):
            return False
        if YES.search(v) or words.search(v):
            return True
    return bool(words.search(text))


def _len_m(v) -> float | None:
    """Длина из характеристики: мм (>100) или м."""
    x = _range_mean(str(v)) if v is not None else None
    if x is None:
        return None
    return x / 1000 if x > 100 else x


def attributes(p: dict) -> dict:
    """Нормализованные признаки товара для правил, рекомендаций и расчёта (синтетический и реальный каталог)."""
    ch = {" ".join(k.split()): v for k, v in char_map(p).items()}
    name = p.get("name", "")
    low_name = name.lower()
    desc = (p.get("description") or "").lower()
    text = low_name + " " + desc

    a: dict = {}
    a["moisture_resistant"] = _flag(ch, ["Влагостойкость", "Влагостойкость краски", "Влагостойкость обоев",
                                         "Тип помещения"], text, MOIST_WORDS)
    wet_room = (ch.get("Тип помещения") or "").lower()
    if "влаж" in wet_room and "не" not in wet_room.split("влаж")[0][-4:]:
        a["moisture_resistant"] = True
    washable_vals = " ".join(str(ch.get(k, "")) for k in ("Влагостойкость обоев", "Моющиеся", "Моющаяся", "Дополнительно"))
    a["washable"] = bool(re.search(r"(?<!не )моющ", text + " " + washable_vals.lower())) or \
        ch.get("Класс стойкости к мокрому истиранию") in ("1", "2")
    a["kids_safe"] = bool(re.search(r"для детск|\be1\b|экологичн", text)) or ch.get("Для детских") == "да"
    a["frost_resistant"] = _flag(ch, ["Морозостойкость"], text, re.compile(r"(?<!не )морозостойк", re.I))
    a["antislip"] = "противоскольз" in text
    a["paintable"] = bool(re.search(r"под покраск|под окраск", text)) or YES.search(ch.get("Подходит под окраску", "")) is not None
    a["warm_floor_ok"] = bool(re.search(r"тепл\w* пол", text)) or YES.search(
        ch.get("Применим с теплыми полами", "") or ch.get("Совместимость с теплым полом", "")) is not None
    a["wear_class"] = to_float(ch.get("Износостойкость") or ch.get("Класс износостойкости"))

    vol = to_float(ch.get("Литраж банки") or ch.get("Объем") or ch.get("Объём"))
    name_vol = _find(r"л\b", low_name)  # литраж в названии надёжнее характеристик
    a["volume_l"] = name_vol or (vol if vol and vol <= 60 else None)
    w = _find(r"кг", low_name)
    if w is None:
        g = _find(r"г\b", low_name)
        w = g / 1000 if g else None
    if w is None:
        wv = to_float(ch.get("Вес"))
        if wv:
            w = wv / 1000 if wv > 100 else wv
    a["weight_kg"] = w
    a["consumption"] = parse_consumption(ch.get("Расход") or ch.get("Расход материала") or "")

    a["roll_width_m"] = _len_m(ch.get("Ширина рулона") or ch.get("Ширина"))
    a["roll_length_m"] = _len_m(ch.get("Длина рулона") or ch.get("Длина"))
    if a["roll_width_m"] is None or a["roll_width_m"] > 6:
        m = re.search(NUM + r"\s*[xх×]\s*" + NUM + r"\s*м\b", low_name)
        if m:
            x, y = (float(m.group(i).replace(",", ".")) for i in (1, 2))
            a["roll_width_m"], a["roll_length_m"] = min(x, y), max(x, y)
    a["rapport_m"] = (to_float(ch.get("Раппорт")) or 0) / 100
    a["coverage_m2"] = to_float(ch.get("Площадь оклейки"))
    heat = re.findall(NUM + r"(?:\s*[-–]\s*" + NUM + r")?\s*м2", low_name)
    if heat:
        a["coverage_m2"] = max(float((h[1] or h[0]).replace(",", ".")) for h in heat)
    elif to_float(ch.get("Площадь обогрева")) and to_float(ch.get("Площадь обогрева")) <= 20:
        a["coverage_m2"] = to_float(ch.get("Площадь обогрева"))
    a["length_m"] = _len_m(ch.get("Длина")) or _find(r"м\b", low_name)
    a["cable_pack_m"] = to_float(ch.get("Метраж упаковки"))
    L, W = _len_m(ch.get("Длина")), _len_m(ch.get("Ширина"))
    a["sheet_area_m2"] = round(L * W, 3) if L and W and L * W > 0.3 else None
    if a["sheet_area_m2"] is None:  # размеры листа только в названии: «1500х1000мм»
        m = re.search(r"(\d{3,4})\s*[xх×]\s*(\d{3,4})(?:\s*[xх×]\s*\d+[,.]?\d*)?\s*мм", low_name)
        if m and int(m.group(1)) * int(m.group(2)) / 1e6 > 0.3:
            a["sheet_area_m2"] = round(int(m.group(1)) * int(m.group(2)) / 1e6, 3)
    a["pack_qty"] = to_float(ch.get("Количество в упаковке")) or _find(r"шт", low_name)
    return a


class Catalog:
    def __init__(self, products: list[dict]):
        self.products: dict[int, dict] = {}
        for p in products:
            self.add(p)

    def add(self, p: dict):
        p = dict(p)
        p["_attrs"] = attributes(p)
        p["_text"] = product_text(p)
        self.products[int(p["id"])] = p
        return p

    def get(self, pid: int) -> dict | None:
        return self.products.get(int(pid))

    def __len__(self):
        return len(self.products)

    def __iter__(self):
        return iter(self.products.values())

    @classmethod
    def load(cls, path: Path = CATALOG_PATH) -> "Catalog":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):  # формат ответа API: {"items": [...]} или {"data": [...]}
            data = data.get("items") or data.get("data") or []
        return cls(data)


def public(p: dict) -> dict:
    """Карточка без служебных полей."""
    return {k: v for k, v in p.items() if not k.startswith("_")}
