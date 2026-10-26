"""Клиент локальной LLM (Ollama) для закрытого контура. Без Ollama сервис работает на правилах и шаблонах."""
import json
import logging
import time

import httpx

from .config import LLM_ENABLED, OLLAMA_MODEL, OLLAMA_URL

log = logging.getLogger(__name__)
_state = {"checked": 0.0, "ok": False}


def available() -> bool:
    if LLM_ENABLED == "off":
        return False
    if time.time() - _state["checked"] < 60:
        return _state["ok"]
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        names = [m["name"] for m in r.json().get("models", [])]
        _state["ok"] = any(n.startswith(OLLAMA_MODEL.split(":")[0]) for n in names)
    except Exception:
        _state["ok"] = False
    _state["checked"] = time.time()
    return _state["ok"]


def generate(prompt: str, system: str = "", json_mode=False, timeout=60.0, temperature=0.2) -> str | None:
    if not available():
        return None
    body = {"model": OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": temperature, "num_ctx": 8192}}
    if json_mode:
        body["format"] = "json"
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=timeout)
        r.raise_for_status()
        return r.json().get("response")
    except Exception as e:
        log.warning("Ollama error: %s", e)
        return None


def generate_json(prompt: str, system: str = "") -> dict | None:
    out = generate(prompt, system, json_mode=True)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None
