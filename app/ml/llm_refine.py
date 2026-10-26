"""Уточнение неоднозначных товаров локальной LLM (Ollama).

Применяется только к товарам «на границе порога»: LLM выбирает виды работ из топ-кандидатов модели
(с описаниями из справочника). Ответ ограничен списком кандидатов — LLM не может придумать новый вид работ.
Без доступной LLM возвращает None, и остаётся решение модели.
"""
import numpy as np

from .. import llm
from ..catalog import product_text
from ..taxonomy import work_types

SYSTEM = ("Ты — эксперт по ремонтно-отделочным работам и строительному ассортименту. Отвечай строго JSON "
          "без пояснений вне JSON.")


def is_uncertain(P_row: np.ndarray, thresholds: np.ndarray) -> bool:
    return bool(np.any((P_row >= 0.6 * thresholds) & (P_row < 1.3 * thresholds)))


def refine(product: dict, P_row: np.ndarray, classes: list[str], top_k: int = 6) -> list[str] | None:
    if not llm.available():
        return None
    desc = {w["id"]: w for w in work_types()}
    top = [classes[c] for c in np.argsort(-P_row)[:top_k]]
    options = "\n".join(f"- {c}: {desc[c]['name']} — {desc[c]['description'][:220]}" for c in top)
    prompt = (f"Товар строительного магазина:\n{product_text(product)[:1500]}\n\n"
              f"Возможные виды работ (код: описание):\n{options}\n\n"
              "Правила: товар относится к виду работ, если он основной материал, расходник или специализированный "
              "инструмент этой работы. Можно выбрать несколько видов или ни одного (если товар не для ремонта "
              "помещений). Верни JSON {\"work_types\": [коды из списка], \"reason\": \"кратко\"}.")
    out = llm.generate_json(prompt, SYSTEM)
    if not out or not isinstance(out.get("work_types"), list):
        return None
    return [w for w in out["work_types"] if w in top]
