"""RepairCalc — микросервис умных калькуляторов ремонта (FastAPI, stateless, REST/JSON)."""
import json
import logging
from contextlib import asynccontextmanager
import time
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, nlp, rag
from .calc.estimate import estimate, money, product_brief
from .calc.formulas import BASIS, compute
from .catalog import public
from .config import DATASET, MODEL_DIR, ROOT
from .mock_stand import router as stand_router
from .recommend import pick
from .service import all_work_types, get_index, suitable_rooms
from .taxonomy import rooms as taxonomy_rooms
from .taxonomy import taxonomy, work_type_name

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app):
    t = time.perf_counter()
    get_index()  # загрузка каталога, модели и авторазметка при старте
    rag.chunks()
    logging.info("RepairCalc ready in %.1fs", time.perf_counter() - t)
    yield


app = FastAPI(lifespan=lifespan, title="RepairCalc API", version="1.0.0",
              description="Микросервис умных калькуляторов ремонта: ML-матчинг каталога к видам работ, "
                          "подбор материалов под помещение и расчёт сметы.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(stand_router)

RoomType = Literal["living", "bedroom", "kids", "kitchen", "bathroom", "toilet", "hallway", "balcony"]


class RoomIn(BaseModel):
    type: RoomType
    area: float | None = Field(None, gt=0, le=500, description="Площадь пола, м²")
    length: float | None = Field(None, gt=0, le=50)
    width: float | None = Field(None, gt=0, le=50)
    height: float = Field(2.7, gt=1.8, le=6)
    doors: int | None = Field(None, ge=0, le=6)
    windows: int | None = Field(None, ge=0, le=10)
    name: str | None = None
    wall_finish: Literal["paint", "wallpaper", "tile", "panels"] | None = None
    floor_finish: Literal["laminate", "tile", "linoleum", "spc"] | None = None
    humidity: Literal["low", "medium", "high"] | None = None


class EstimateIn(BaseModel):
    object_type: Literal["apartment", "studio", "house"] = "apartment"
    repair_type: Literal["cosmetic", "capital", "designer"] = "capital"
    rooms: list[RoomIn] = Field(..., min_length=1, max_length=30)
    region_id: int | None = 1
    explain: bool = False
    include_optional: bool = True

    model_config = {"json_schema_extra": {"example": {
        "object_type": "apartment", "repair_type": "capital", "explain": True,
        "rooms": [{"type": "bathroom", "area": 6, "humidity": "high"}, {"type": "kitchen", "length": 3, "width": 4}]}}}


class ProductCalcIn(BaseModel):
    area: float | None = Field(None, gt=0, description="Площадь, м²")
    length: float | None = Field(None, gt=0, description="Длина комнаты / погонные метры, м")
    width: float | None = Field(None, gt=0, description="Ширина комнаты, м")
    wall_width: float | None = Field(None, gt=0, description="Ширина стены, м")
    wall_height: float | None = Field(None, gt=0, description="Высота стены, м")
    openings_area: float = Field(0, ge=0, description="Площадь проёмов, м²")
    points: int | None = Field(None, gt=0, description="Число электроточек (для кабеля)")
    count: int | None = Field(None, gt=0, description="Количество штук (двери, розетки)")
    diagonal: bool = False
    layers: int = Field(2, ge=1, le=4)
    with_companions: bool = True
    region_id: int | None = 1

    model_config = {"json_schema_extra": {"example": {"wall_width": 3.2, "wall_height": 2.7}}}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")


@app.get("/health")
def health():
    idx = get_index()
    return {"status": "ok", "dataset": DATASET, "products": len(idx.catalog), "model": idx.matcher.mode,
            "embeddings": idx.embedder.available, "llm": llm.available()}


@app.get("/api/v1/meta")
def meta():
    tx = taxonomy()
    model_meta = json.loads((MODEL_DIR / "meta.json").read_text()) if (MODEL_DIR / "meta.json").exists() else {}
    return {"work_types": all_work_types(), "rooms": tx["rooms"], "object_types": tx["object_types"],
            "repair_types": tx["repair_types"], "stages": tx["stages"], "model": model_meta, "dataset": DATASET,
            "llm": {"available": llm.available()}}


# ---------------- Калькуляторы ----------------

@app.post("/api/v1/calc/general", tags=["calc"], summary="Общий калькулятор: объект + тип ремонта + помещения → смета")
def calc_general(req: EstimateIn):
    rooms = [r.model_dump(exclude_none=True) for r in req.rooms]
    for r in rooms:
        if not r.get("area") and not (r.get("length") and r.get("width")):
            raise HTTPException(422, "для помещения нужна площадь или длина и ширина")
        r.setdefault("area", (r.get("length") or 0) * (r.get("width") or 0))
    res = estimate(get_index(), req.object_type, req.repair_type, rooms, req.region_id, req.include_optional)
    if req.explain:
        res["explanations"] = [rag.explain_room(r, res["repair_type_name"]) for r in res["rooms"]]
    return res


@app.post("/api/v1/calc/room", tags=["calc"], summary="Калькулятор специфики комнаты: рекомендации материалов")
def calc_room(room: RoomIn, repair_type: Literal["cosmetic", "capital", "designer"] = "capital",
              object_type: Literal["apartment", "studio", "house"] = "apartment", region_id: int | None = 1):
    r = room.model_dump(exclude_none=True)
    if not r.get("area") and not (r.get("length") and r.get("width")):
        raise HTTPException(422, "нужна площадь или длина и ширина")
    r.setdefault("area", (r.get("length") or 0) * (r.get("width") or 0))
    res = estimate(get_index(), object_type, repair_type, [r], region_id)
    room_res = res["rooms"][0]
    return {"room": room_res, "total": res["total"], "explanation": rag.explain_room(room_res, res["repair_type_name"]),
            "warnings": res["warnings"], "elapsed_ms": res["elapsed_ms"]}


@app.post("/api/v1/calc/text", tags=["calc"], summary="Смета по текстовому запросу (LLM / правила)")
def calc_text(text: str = Body(..., embed=True, examples=["Квартира, капремонт: санузел 6 м², кухня 3 на 4"])):
    parsed = nlp.parse(text)
    if not parsed["rooms"]:
        return {"parsed": parsed, "estimate": None, "message": "не удалось найти помещения и площади в запросе"}
    res = estimate(get_index(), parsed["object_type"], parsed["repair_type"], parsed["rooms"])
    return {"parsed": parsed, "estimate": res}


# ---------------- Карточка товара ----------------

COMPANIONS = {
    "tile": [("tile_adhesive", "area"), ("grout", "area"), ("primer", "area")],
    "laminate": [("underlay", "area"), ("skirting", "perimeter")],
    "wallpaper": [("wallpaper_glue", "area"), ("primer", "area")],
    "paint": [("primer", "area"), ("tool", "one")],
    "drywall_sheet": [("profile", "area"), ("fastener", "area")],
    "plaster_mix": [("primer", "area")], "putty": [("primer", "area")], "self_leveling_mix": [("primer", "area")],
    "linoleum": [("skirting", "perimeter")],
    "waterproofing_mix": [("waterproofing_tape", "perimeter"), ("primer", "area")],
    "heating_mat": [("thermostat", "one"), ("tile_adhesive", "area")],
    "door": [("door_part", "one"), ("foam", "one")],
    "tile_adhesive": [("grout", "area"), ("primer", "area")],
}


@app.get("/api/v1/product/{pid}", tags=["product"])
def product(pid: int):
    p = get_index().catalog.get(pid)
    if not p:
        raise HTTPException(404, "товар не найден")
    return {"product": public(p), "annotation": get_index().describe(p, with_similar=True),
            "calc_basis": next((b for b, ks in BASIS.items() if p["_kind"] in ks), "count")}


@app.post("/api/v1/product/{pid}/calc", tags=["product"], summary="Расчёт количества и стоимости товара под размеры")
def product_calc(pid: int, req: ProductCalcIn):
    idx = get_index()
    p = idx.catalog.get(pid)
    if not p:
        raise HTTPException(404, "товар не найден")
    kind = p["_kind"]
    perimeter = None
    if req.area:
        area = req.area
    elif req.length and req.width:
        area, perimeter = req.length * req.width, 2 * (req.length + req.width)
    elif req.wall_width and req.wall_height:
        area, perimeter = req.wall_width * req.wall_height, req.wall_width
    else:
        area = None
    if area is not None:
        area = max(area - req.openings_area, 0)
    ctx = {"diagonal": req.diagonal, "layers": req.layers, "height": req.wall_height or 2.7,
           "wall_length": req.wall_width, "length": req.length, "width": req.width}
    basis_type = next((b for b, ks in BASIS.items() if kind in ks), "count")
    if basis_type == "area":
        if area is None:
            raise HTTPException(422, "для этого товара нужны размеры: area, или length+width, или wall_width+wall_height")
        basis = area
    elif basis_type == "length":
        basis = req.length if (req.length and not req.width) else perimeter
        if not basis:
            raise HTTPException(422, "для этого товара нужна длина (length) или размеры комнаты")
    elif basis_type == "points":
        basis = req.points or 10
    else:
        basis = req.count or 1
    need = compute(kind, basis, p["_attrs"], p, ctx)
    price = money(p.get("result_price") or 0)
    res = {"product": product_brief(p), "kind": kind, "work_types": p["_wt"], "basis": {"type": basis_type, "value": round(basis, 3)},
           "qty": need.qty, "unit": p.get("unit"), "amount": need.amount, "formula": need.formula,
           "assumptions": need.assumptions, "unit_price": str(price), "cost": str(money(Decimal(str(need.qty)) * price))}
    if req.with_companions and kind in COMPANIONS and p["_wt"]:
        wt = max(p["_wt"], key=lambda w: p["_ml"]["proba"].get(w, 0))
        comps, total = [], Decimal(res["cost"])
        for ckind, cbasis in COMPANIONS[kind]:
            ranked, _ = pick(idx, wt, ckind, [], {}, "capital", req.region_id)
            if not ranked:
                continue
            q = ranked[0][1]
            b = area if cbasis == "area" else (perimeter or (area ** 0.5 * 4 if area else 1)) if cbasis == "perimeter" else 1
            n = compute(ckind, b, q["_attrs"], q, ctx)
            cost = money(Decimal(str(n.qty)) * money(q.get("result_price") or 0))
            total += cost
            comps.append({"product": product_brief(q), "kind": ckind, "qty": n.qty, "unit": q.get("unit"),
                          "formula": n.formula, "cost": str(cost)})
        res["companions"] = comps
        res["total_with_companions"] = str(money(total))
        res["work_type"] = {"id": wt, "name": work_type_name(wt)}
    return res


# ---------------- Каталог / ML ----------------

@app.get("/api/v1/work-types/{wt}/products", tags=["ml"], summary="Ранжированный список товаров для вида работ")
def products_for_work_type(wt: str, limit: int = Query(20, le=200)):
    idx = get_index()
    if wt not in idx.classes:
        raise HTTPException(404, "неизвестный вид работ")
    return {"work_type": {"id": wt, "name": work_type_name(wt)},
            "items": [idx.describe(p) for p in idx.by_work_type(wt, limit)]}


@app.post("/api/v1/admin/suggest", tags=["admin"], summary="ML-подсказка для нового товара (без сохранения)")
def admin_suggest(product: dict = Body(..., examples=[{"name": "Клей для мозаики и стеклянной плитки белый 5 кг",
                                                       "description": "Для бассейнов и душевых"}])):
    from .catalog import attributes, product_text
    p = {"id": -1, "characteristics": [], **product}
    p["_attrs"], p["_text"] = attributes(p), product_text(p)
    idx = get_index()
    Yp, P, kinds, kconf, E = idx.predict([p])
    order = P[0].argsort()[::-1]
    wts = [idx.classes[c] for c in range(len(idx.classes)) if Yp[0, c]]
    p["_emb"] = None if E is None else E[0]
    return {
        "work_types": [{"id": w, "name": work_type_name(w), "proba": round(float(P[0, idx.classes.index(w)]), 3)} for w in wts],
        "top": [{"id": idx.classes[c], "name": work_type_name(idx.classes[c]), "proba": round(float(P[0, c]), 3),
                 "threshold": float(idx.matcher.thresholds[c])} for c in order[:6]],
        "kind": kinds[0], "kind_conf": round(float(kconf[0]), 3),
        "rooms": [{"id": r, "name": taxonomy_rooms()[r]["name"]} for r in suitable_rooms(p["_attrs"], wts)],
        "attributes": p["_attrs"], "similar": idx.similar(p), "llm_used": False,
    }


@app.get("/api/v1/admin/products", tags=["admin"], summary="Каталог с ML-разметкой и фильтрами")
def admin_products(q: str = "", work_type: str = "", kind: str = "", source: str = "",
                   low_conf: bool = False, page: int = 1, per_page: int = Query(30, le=200)):
    idx = get_index()
    items = list(idx.catalog)
    if q:
        items = [p for p in items if q.lower() in p["name"].lower()]
    if work_type:
        items = [p for p in items if work_type in p["_wt"]]
    if kind:
        items = [p for p in items if p["_kind"] == kind]
    if source:
        items = [p for p in items if p["_source"] == source]
    if low_conf:
        items = [p for p in items if not p["_wt"] or max(p["_ml"]["proba"].values()) < 0.6]
    total = len(items)
    items = items[(page - 1) * per_page: page * per_page]
    return {"total": total, "page": page, "items": [idx.describe(p) for p in items]}


@app.post("/api/v1/admin/products/{pid}/bind", tags=["admin"], summary="Ручная привязка товара (приоритет над ML)")
def admin_bind(pid: int, work_types: list[str] | None = Body(None), kind: str | None = Body(None),
               rooms: list[str] | None = Body(None)):
    idx = get_index()
    if not idx.catalog.get(pid):
        raise HTTPException(404, "товар не найден")
    try:
        idx.bind(pid, work_types, kind, rooms)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return idx.describe(idx.catalog.get(pid))


@app.delete("/api/v1/admin/products/{pid}/bind", tags=["admin"])
def admin_unbind(pid: int):
    idx = get_index()
    idx.unbind(pid)
    return idx.describe(idx.catalog.get(pid))


@app.post("/api/v1/admin/ingest", tags=["admin"], summary="Загрузка новых товаров (формат API стенда) с авторазметкой")
def admin_ingest(products: list[dict] = Body(...)):
    t = time.perf_counter()
    out = get_index().ingest(products)
    return {"ingested": len(out), "elapsed_ms": round(1000 * (time.perf_counter() - t), 1), "items": out}


@app.post("/api/v1/admin/sync", tags=["admin"], summary="Синхронизация каталога со стендом (обход дерева + пагинация)")
def admin_sync(base_url: str = Body(..., embed=True, examples=["http://localhost:8000/stand"]),
               category_id: int = Body(1, embed=True), max_products: int = Body(200, embed=True)):
    from scripts.ingest_catalog import fetch_catalog
    t = time.perf_counter()
    try:
        products, log = fetch_catalog(base_url, category_id, max_products, skip_ids=set(get_index().catalog.products))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"стенд недоступен: {e}")
    t_fetch = time.perf_counter() - t
    out = get_index().ingest(products) if products else []
    return {"fetched": len(products), "fetch_s": round(t_fetch, 2), "total_s": round(time.perf_counter() - t, 2),
            "log": log[-20:], "items": out[:50]}


@app.get("/api/v1/admin/stats", tags=["admin"], summary="Покрытие авторазметкой и производительность")
def admin_stats():
    idx = get_index()
    prods = list(idx.catalog)
    auto = [p for p in prods if p["_source"] == "ml" and p["_wt"]]
    low = [p for p in prods if not p["_wt"] or max(p["_ml"]["proba"].values()) < 0.6]
    by_wt = {w: 0 for w in idx.classes}
    for p in prods:
        for w in p["_wt"]:
            by_wt[w] += 1
    return {"products": len(prods), "auto_bound": len(auto), "auto_bound_share": round(len(auto) / max(len(prods), 1), 3),
            "manual_bound": sum(1 for p in prods if p["_source"] == "manual"),
            "no_work_type": sum(1 for p in prods if not p["_wt"]), "low_confidence": len(low),
            "by_work_type": [{"id": w, "name": work_type_name(w), "count": c} for w, c in by_wt.items()],
            "timing": idx.stats}


@app.get("/api/v1/admin/metrics", tags=["admin"], summary="Отчёт оценки качества ML (reports/metrics.json)")
def admin_metrics():
    f = ROOT / "reports" / f"metrics_{DATASET}.json"
    if not f.exists():
        raise HTTPException(404, "отчёт не сформирован: python -m eval.evaluate")
    return json.loads(f.read_text())


@app.get("/api/v1/knowledge/search", tags=["rag"])
def knowledge_search(q: str, k: int = 4):
    return rag.search(q, k)


app.mount("/ui", StaticFiles(directory=ROOT / "static", html=True), name="ui")
