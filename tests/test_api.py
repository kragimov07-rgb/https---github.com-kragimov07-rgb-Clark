import json

import pytest
from fastapi.testclient import TestClient

from app.config import NEW_PRODUCTS_PATH
from app.main import app
from app.nlp import parse_rules


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["products"] > 1000


def test_demo_scenario_bathroom(client):
    """Демо из кейса: квартира → капремонт → санузел 6 м², высокая влажность."""
    r = client.post("/api/v1/calc/general", json={"object_type": "apartment", "repair_type": "capital", "explain": True,
                                                  "rooms": [{"type": "bathroom", "area": 6, "humidity": "high"}]}).json()
    assert float(r["total"]) > 0
    lines = r["rooms"][0]["lines"]
    kinds = {l["kind"] for l in lines}
    assert {"tile", "tile_adhesive", "grout", "waterproofing_mix", "drywall_sheet"} <= kinds
    gkl = [l for l in lines if l["kind"] == "drywall_sheet"]
    assert all("ГКЛВ" in l["product"]["name"] or "влаго" in l["product"]["name"].lower() for l in gkl)
    assert r["explanations"][0]["text"]
    total = sum(float(l["cost"]) for l in lines)
    assert total == pytest.approx(float(r["total"]), abs=0.01)


def test_cosmetic_cheaper_than_designer(client):
    body = {"object_type": "apartment", "rooms": [{"type": "living", "area": 18}]}
    cos = float(client.post("/api/v1/calc/general", json={**body, "repair_type": "cosmetic"}).json()["total"])
    des = float(client.post("/api/v1/calc/general", json={**body, "repair_type": "designer"}).json()["total"])
    assert cos < des


def test_product_calc_with_companions(client):
    items = client.get("/api/v1/admin/products", params={"q": "Плитка настенная"}).json()["items"]
    r = client.post(f"/api/v1/product/{items[0]['id']}/calc", json={"wall_width": 3.2, "wall_height": 2.7}).json()
    assert r["qty"] > 0 and r["companions"]
    assert {c["kind"] for c in r["companions"]} >= {"tile_adhesive", "grout"}


def test_validation(client):
    assert client.post("/api/v1/calc/general", json={"rooms": [{"type": "kitchen"}]}).status_code == 422
    assert client.post("/api/v1/product/999999999/calc", json={"area": 5}).status_code == 404


def test_suggest_and_ingest_new_products(client):
    r = client.post("/api/v1/admin/suggest", json={"name": "Затирка эпоксидная для швов плитки 2,5 кг"}).json()
    assert r["work_types"][0]["id"] == "tiling"
    new = json.loads(NEW_PRODUCTS_PATH.read_text())[:20]
    out = client.post("/api/v1/admin/ingest", json=new).json()
    assert out["ingested"] == 20


def test_manual_binding_overrides_ml(client):
    pid = client.get("/api/v1/admin/products", params={"q": "Перфоратор"}).json()["items"][0]["id"]
    r = client.post(f"/api/v1/admin/products/{pid}/bind", json={"work_types": ["demolition"]}).json()
    assert r["source"] == "manual" and [w["id"] for w in r["work_types"]] == ["demolition"]
    r = client.delete(f"/api/v1/admin/products/{pid}/bind").json()
    assert r["source"] == "ml"


def test_text_parser():
    p = parse_rules("Квартира, капремонт: санузел 6 м², кухня 3 на 4")
    assert p["repair_type"] == "capital"
    assert p["rooms"][0] == {"type": "bathroom", "area": 6.0}
    assert p["rooms"][1]["area"] == 12.0
