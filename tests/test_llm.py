"""Интеграция с локальной LLM (Ollama) на фейковом сервере с тем же API.

Проверяет, что при доступной модели пояснения сметы и разбор текста идут через LLM, а при недоступной —
сервис откатывается на шаблоны и правила (закрытый контур без LLM тоже должен работать).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import llm, nlp, rag

CALLS = []


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "qwen2.5:7b-instruct"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        CALLS.append(req)
        if req.get("format") == "json":
            out = {"object_type": "apartment", "repair_type": "capital",
                   "rooms": [{"type": "bathroom", "area": 4.5}, {"type": "kitchen", "area": 10, "length": None}]}
            self._send({"response": json.dumps(out)})
        else:
            self._send({"response": "• Влагостойкий ГКЛВ, потому что в санузле высокая влажность."})


@pytest.fixture
def fake_ollama(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(llm, "OLLAMA_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(llm, "LLM_ENABLED", "auto")
    monkeypatch.setitem(llm._state, "checked", 0.0)
    CALLS.clear()
    yield srv
    srv.shutdown()


ROOM = {"name": "Санузел (ванная)", "profile": {"humidity": "high", "traffic": "medium", "wet": True},
        "lines": [{"title": "Короб для труб из ГКЛВ", "product": {"name": "гипсокартон влагостойкий"}, "qty": 1,
                   "unit": "шт.", "formula": "2,5 м² × 1,1 / 3 м²", "requirements": {"moisture_resistant": True}}]}


def test_explanation_uses_llm_with_rag_context(fake_ollama):
    out = rag.explain_room(ROOM, "Капитальный")
    assert out["mode"] == "llm" and "ГКЛВ" in out["text"]
    prompt = CALLS[-1]["prompt"]
    assert "База знаний" in prompt and "гипсокартон влагостойкий" in prompt  # RAG-контекст и факты сметы в промпте
    assert out["sources"]


def test_text_parsing_uses_llm_json(fake_ollama):
    res = nlp.parse("капремонт: ванная четыре с половиной метра и кухня десять квадратов")
    assert res["mode"] == "llm"
    assert res["rooms"][0] == {"type": "bathroom", "area": 4.5}
    assert CALLS[-1]["format"] == "json"


def test_fallback_without_llm(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_URL", "http://127.0.0.1:9")  # закрытый порт
    monkeypatch.setitem(llm._state, "checked", 0.0)
    assert rag.explain_room(ROOM, "Капитальный")["mode"] == "template"
    assert nlp.parse("санузел 6 м²")["mode"] == "rules"


def test_llm_refines_uncertain_product_within_candidates(fake_ollama, monkeypatch):
    import numpy as np

    from app.ml import llm_refine

    def fake_json(prompt, system=""):
        assert "Возможные виды работ" in prompt
        return {"work_types": ["tiling", "invented_type"], "reason": "клей для мозаики"}

    monkeypatch.setattr(llm, "generate_json", fake_json)
    classes = ["tiling", "wallpapering", "painting"]
    P = np.array([0.28, 0.2, 0.05])
    assert llm_refine.is_uncertain(P, np.array([0.3, 0.3, 0.4]))
    out = llm_refine.refine({"name": "клей для мозаики 5 кг", "characteristics": []}, P, classes, top_k=3)
    assert out == ["tiling"]  # выдуманный код отброшен: LLM выбирает только из кандидатов модели
