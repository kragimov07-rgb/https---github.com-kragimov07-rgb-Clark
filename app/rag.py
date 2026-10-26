"""RAG-пояснения «почему эти материалы»: поиск по базе знаний (data/knowledge) + локальная LLM.

Поиск: фрагменты базы знаний (разделы ##) -> эмбеддинги e5 -> косинусная близость (in-memory; при росте базы
заменяется на FAISS/Qdrant без изменения интерфейса). Генерация: Ollama; без неё — пояснение собирается
из найденных фрагментов и требований помещения по шаблону, поэтому ответ есть всегда.
"""
import re
from functools import lru_cache

import numpy as np

from . import llm
from .config import KNOWLEDGE_DIR
from .ml.embed import default_embedder
from .taxonomy import rooms as taxonomy_rooms


@lru_cache
def chunks() -> list[dict]:
    out = []
    for f in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for block in re.split(r"\n(?=## )", f.read_text(encoding="utf-8")):
            if not block.startswith("## "):
                continue
            title, _, body = block[3:].partition("\n")
            out.append({"source": f.name, "title": title.strip(), "text": " ".join(body.split())})
    return out


@lru_cache
def _matrix():
    emb = default_embedder()
    M = emb.encode([f"{c['title']}. {c['text']}" for c in chunks()])
    emb.save()
    return M


def search(query: str, k: int = 4) -> list[dict]:
    M = _matrix()
    if M is None:  # без эмбеддингов — поиск по пересечению слов
        q = set(re.findall(r"\w{4,}", query.lower()))
        scored = [(len(q & set(re.findall(r"\w{4,}", (c["title"] + c["text"]).lower()))), c) for c in chunks()]
    else:
        v = default_embedder().encode([query])[0]
        scored = list(zip((M @ v).tolist(), chunks()))
    scored.sort(key=lambda x: -x[0])
    return [{**c, "score": round(float(s), 3)} for s, c in scored[:k]]


SYSTEM = ("Ты — консультант строительного магазина. Объясняй кратко и по делу, на русском, только на основе "
          "переданных фактов и фрагментов базы знаний. Не выдумывай характеристики товаров.")


def explain_room(room: dict, repair_name: str) -> dict:
    """Пояснение по помещению сметы: почему выбраны такие материалы."""
    rname = room["name"]
    prof = room["profile"]
    key_lines = [l for l in room["lines"] if not l.get("optional")][:14]
    query = f"{rname} {repair_name} ремонт: " + ", ".join(l["title"] for l in key_lines)
    stem = rname.lower().split()[0][:5]
    found = [c for c in search(query, k=8)  # описания других помещений не нужны
             if c["source"] != "rooms.md" or stem in c["title"].lower() or c["title"] == "Типы ремонта"][:4]
    facts = []
    for l in key_lines:
        req = ", ".join(k for k, v in (l.get("requirements") or {}).items() if v)
        facts.append(f"- {l['title']}: {l['product']['name']}, {l['qty']} {l['unit'] or ''} ({l['formula']})"
                     + (f"; требования: {req}" if req else ""))
    context = "\n".join(f"[{c['title']}] {c['text']}" for c in found)
    prompt = (f"Помещение: {rname}, ремонт: {repair_name}. Влажность: {prof.get('humidity')}, "
              f"нагрузка: {prof.get('traffic')}.\nПозиции сметы:\n" + "\n".join(facts) +
              f"\n\nБаза знаний:\n{context}\n\nОбъясни в 4–6 пунктах, почему подобраны именно эти материалы "
              "и на что обратить внимание при покупке.")
    text = llm.generate(prompt, SYSTEM)
    mode = "llm"
    if not text:
        mode = "template"
        text = template_explanation(room, found)
    return {"room": rname, "mode": mode, "text": text,
            "sources": [{"title": c["title"], "source": c["source"], "score": c["score"]} for c in found]}


REQ_TEXT = {"moisture_resistant": "влагостойкие материалы", "frost_resistant": "морозостойкие материалы",
            "wear_class_min": "класс износостойкости не ниже {}"}


def template_explanation(room: dict, found: list[dict]) -> str:
    prof = room["profile"]
    lines = []
    if prof.get("humidity") == "high" or prof.get("wet"):
        lines.append("• Помещение с высокой влажностью — подобраны только влагостойкие материалы: ГКЛВ, плитка, "
                     "водоотталкивающая затирка, санитарный герметик, электрофурнитура IP44.")
    if prof.get("grease"):
        lines.append("• Кухня: стены — моющиеся покрытия, пол — износостойкий и водостойкий.")
    if prof.get("eco"):
        lines.append("• Детская: приоритет экологичным материалам (класс E1) и моющимся покрытиям.")
    if prof.get("cold"):
        lines.append("• Балкон: утепление и морозостойкие материалы из-за перепадов температур.")
    reqs = set()
    for l in room["lines"]:
        for k, v in (l.get("requirements") or {}).items():
            if v:
                reqs.add(REQ_TEXT.get(k, k).format(v))
    if reqs:
        lines.append("• Применённые ограничения подбора: " + ", ".join(sorted(reqs)) + ".")
    for c in found[:3]:
        first = re.split(r"(?<=[.!?])\s", c["text"])
        lines.append(f"• {c['title']}: " + " ".join(first[:2]))
    lines.append("• Количество рассчитано по нормам расхода с запасом на подрезку и округлено до целых упаковок.")
    return "\n".join(lines)


def room_types_from_text(text: str) -> list[str]:
    t = text.lower()
    keys = {"bathroom": ["санузел", "ванн", "душ"], "toilet": ["туалет"], "kitchen": ["кухн"], "kids": ["детск"],
            "bedroom": ["спальн"], "living": ["гостин", "зал", "комнат"], "hallway": ["прихож", "коридор"],
            "balcony": ["балкон", "лоджи"]}
    return [r for r, ws in keys.items() if any(w in t for w in ws) and r in taxonomy_rooms()]


def explain_product_fit(p: dict, room_type: str) -> list[dict]:
    q = f"{p['name']} {taxonomy_rooms().get(room_type, {}).get('name', '')}"
    return search(q, k=2)


def similarity_matrix_ok() -> bool:
    return isinstance(_matrix(), np.ndarray)
