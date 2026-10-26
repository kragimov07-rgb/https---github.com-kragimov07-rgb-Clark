"""Извлечение параметров ремонта из текстового запроса: «квартира, капремонт, санузел 6 м² и кухня 3x4».

Правила (регулярные выражения) работают всегда; если доступна локальная LLM, она уточняет результат.
"""
import re

from . import llm
from .taxonomy import rooms as taxonomy_rooms

ROOM_WORDS = [
    ("bathroom", r"санузел|ванн\w*|душев\w*"), ("toilet", r"туалет\w*"), ("kitchen", r"кухн\w*"),
    ("kids", r"детск\w*"), ("bedroom", r"спальн\w*"), ("living", r"гостин\w*|зал\b|комнат\w*"),
    ("hallway", r"прихож\w*|коридор\w*"), ("balcony", r"балкон\w*|лоджи\w*"),
]
NUM = r"(\d+(?:[.,]\d+)?)"


def _f(s):
    return float(s.replace(",", "."))


def parse_rules(text: str) -> dict:
    t = text.lower().replace("ё", "е")
    obj = "house" if re.search(r"\bдом\w*|коттедж", t) else "studio" if "студи" in t else "apartment"
    rep = ("designer" if re.search(r"дизайн", t) else
           "capital" if re.search(r"капит|капремонт|под ключ|с нуля|черновой", t) else
           "cosmetic" if re.search(r"космет|освеж|обнов", t) else "capital")
    rooms = []
    matches = list(re.finditer("|".join(f"(?P<{k}>{v})" for k, v in ROOM_WORDS), t))
    for i, m in enumerate(matches):
        rtype = m.lastgroup
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        tail = t[m.end():min(end, m.end() + 40)]  # параметры комнаты — до упоминания следующей
        room = {"type": rtype}
        dims = re.search(NUM + r"\s*(?:x|х|\*|на)\s*" + NUM, tail)
        area = re.search(NUM + r"\s*(?:м2|м²|кв\.?\s*м|квадрат|метр)", tail)
        if dims:
            room["length"], room["width"] = _f(dims.group(1)), _f(dims.group(2))
            room["area"] = round(room["length"] * room["width"], 2)
        elif area:
            room["area"] = _f(area.group(1))
        if re.search(r"влажн|сыр", tail):
            room["humidity"] = "high"
        if "area" in room:
            rooms.append(room)
    if not rooms:
        m = re.search(NUM + r"\s*(?:м2|м²|кв)", t)
        if m:
            rooms.append({"type": "living", "area": _f(m.group(1))})
    wishes = {}
    if re.search(r"плитк|кафел", t):
        wishes["tile"] = True
    if re.search(r"обо[ия]", t):
        wishes["wall_finish"] = "wallpaper"
    if re.search(r"покрас|краск", t):
        wishes["wall_finish"] = "paint"
    if "ламинат" in t:
        wishes["floor_finish"] = "laminate"
    if "линолеум" in t:
        wishes["floor_finish"] = "linoleum"
    for r in rooms:
        if r["type"] not in ("bathroom", "toilet"):
            if "wall_finish" in wishes:
                r["wall_finish"] = wishes["wall_finish"]
            if "floor_finish" in wishes:
                r["floor_finish"] = wishes["floor_finish"]
    return {"object_type": obj, "repair_type": rep, "rooms": rooms}


def parse(text: str) -> dict:
    res = parse_rules(text)
    res["mode"] = "rules"
    if llm.available():
        prompt = (
            "Извлеки параметры ремонта из запроса и верни JSON вида "
            '{"object_type": "apartment|studio|house", "repair_type": "cosmetic|capital|designer", '
            '"rooms": [{"type": "' + "|".join(taxonomy_rooms()) + '", "area": число_м2, '
            '"length": число_или_null, "width": число_или_null}]}.\n'
            f"Черновик по правилам: {res}\nЗапрос: {text}")
        out = llm.generate_json(prompt)
        if out and isinstance(out.get("rooms"), list) and out["rooms"]:
            ok = [r for r in out["rooms"] if r.get("type") in taxonomy_rooms() and (r.get("area") or 0) > 0]
            if ok:
                res = {"object_type": out.get("object_type", res["object_type"]),
                       "repair_type": out.get("repair_type", res["repair_type"]),
                       "rooms": [{k: v for k, v in r.items() if v is not None} for r in ok], "mode": "llm"}
    return res
