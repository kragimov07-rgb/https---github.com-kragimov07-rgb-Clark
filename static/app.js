const API = location.origin;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const rub = v => Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let META = null;

async function api(path, body, method) {
  const r = await fetch(API + path, {
    method: method || (body !== undefined ? "POST" : "GET"),
    headers: { "content-type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
const wtName = id => (META?.work_types.find(w => w.id === id) || {}).name || id;

// ---------- вкладки ----------
$$("#tabs button").forEach(b => b.onclick = () => {
  $$("#tabs button").forEach(x => x.classList.toggle("active", x === b));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "admin") loadAdmin();
  if (b.dataset.tab === "quality") loadQuality();
});

// ---------- смета ----------
function addRoom(r = {}) {
  const el = $("#roomTpl").content.firstElementChild.cloneNode(true);
  $(".r-type", el).value = r.type || "living";
  if (r.area) $(".r-area", el).value = r.area;
  if (r.length) $(".r-len", el).value = r.length;
  if (r.width) $(".r-wid", el).value = r.width;
  if (r.humidity) $(".r-hum", el).value = r.humidity;
  if (r.wall_finish) $(".r-wall", el).value = r.wall_finish;
  if (r.floor_finish) $(".r-floor", el).value = r.floor_finish;
  $(".r-del", el).onclick = () => el.remove();
  $("#rooms").append(el);
}
function readRooms() {
  return $$("#rooms .room").map(el => {
    const r = { type: $(".r-type", el).value };
    const n = (c, k) => { const v = parseFloat($(c, el).value); if (v > 0) r[k] = v; };
    n(".r-area", "area"); n(".r-len", "length"); n(".r-wid", "width");
    for (const [c, k] of [[".r-hum", "humidity"], [".r-wall", "wall_finish"], [".r-floor", "floor_finish"]])
      if ($(c, el).value) r[k] = $(c, el).value;
    return r;
  }).filter(r => r.area || (r.length && r.width));
}
$("#addRoom").onclick = () => addRoom();
$("#demo1").onclick = e => {
  e.preventDefault(); $("#rooms").innerHTML = ""; $("#obj").value = "apartment"; $("#rep").value = "capital";
  addRoom({ type: "bathroom", area: 6, humidity: "high" }); calc();
};
$("#nlBtn").onclick = async () => {
  const text = $("#nl").value.trim(); if (!text) return;
  const r = await api("/api/v1/calc/text", { text });
  $("#obj").value = r.parsed.object_type; $("#rep").value = r.parsed.repair_type;
  $("#rooms").innerHTML = ""; r.parsed.rooms.forEach(addRoom);
  if (r.estimate) renderEstimate(r.estimate, `Разобрано (${r.parsed.mode === "llm" ? "LLM" : "правила"})`);
};
$("#calcBtn").onclick = () => calc();

async function calc() {
  const rooms = readRooms();
  if (!rooms.length) { $("#result").innerHTML = `<div class="warn">Добавьте хотя бы одно помещение с площадью или размерами</div>`; return; }
  const btn = $("#calcBtn"); btn.disabled = true; btn.textContent = "Считаем…";
  try {
    const r = await api("/api/v1/calc/general", { object_type: $("#obj").value, repair_type: $("#rep").value, rooms, explain: $("#explain").checked });
    renderEstimate(r);
  } catch (e) { $("#result").innerHTML = `<div class="warn">${esc(e.message)}</div>`; }
  finally { btn.disabled = false; btn.textContent = "Рассчитать смету"; }
}

function renderEstimate(r, note = "") {
  const max = Math.max(...r.by_work_type.map(w => +w.cost), 1);
  const expl = Object.fromEntries((r.explanations || []).map(e => [e.room, e]));
  $("#result").innerHTML = `
    <div class="total"><span class="sum">${rub(r.total)}</span>
      <span class="muted">${esc(r.object_type_name)} · ${esc(r.repair_type_name)} ремонт · ${r.lines_count} позиций · расчёт ${r.elapsed_ms} мс ${note ? "· " + esc(note) : ""}</span></div>
    <div class="muted">${esc(r.disclaimer)}</div>
    ${r.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("")}
    <h3>Структура затрат по видам работ</h3>
    <div class="bars">${r.by_work_type.map(w => `<div class="bar"><span>${esc(w.name)}</span><span class="track"><span class="fill" style="width:${(100 * w.cost / max).toFixed(1)}%"></span></span><span class="v">${rub(w.cost)}</span></div>`).join("")}</div>
    ${r.rooms.map((room, i) => `
      <details class="roomres" ${i === 0 ? "open" : ""}>
        <summary><span>${esc(room.name)} · ${room.geometry.floor_m2} м² пола · ${room.geometry.walls_m2} м² стен</span><span>${rub(room.total)}</span></summary>
        ${expl[room.name] ? `<div class="explain"><b>Почему эти материалы</b> <span class="muted">(${expl[room.name].mode === "llm" ? "LLM + база знаний" : "база знаний"})</span>\n${esc(expl[room.name].text)}</div>` : ""}
        <div class="tablewrap"><table>
          <tr><th>Позиция</th><th>Товар</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">Сумма</th></tr>
          ${room.lines.map(l => `<tr>
            <td>${esc(l.title)}<div><span class="chip ml">${esc(l.work_type_name)}</span>${Object.entries(l.requirements || {}).map(([k, v]) => `<span class="chip">${k === "moisture_resistant" ? "влагостойкость" : k === "frost_resistant" ? "морозостойкость" : k === "wear_class_min" ? "класс ≥ " + v : k}</span>`).join("")}</div></td>
            <td>${esc(l.product.name)}<div class="formula">${esc(l.formula)}</div>
              ${l.alternatives.length ? `<div class="alt">Альтернативы: ${l.alternatives.map(a => `${esc(a.name)} — ${rub(a.cost)}`).join("; ")}</div>` : ""}
              ${l.warnings.map(w => `<div class="alt bad">${esc(w)}</div>`).join("")}</td>
            <td class="num">${l.qty} ${esc(l.unit || "")}</td><td class="num">${rub(l.unit_price)}</td><td class="num"><b>${rub(l.cost)}</b></td></tr>`).join("")}
        </table></div>
      </details>`).join("")}`;
}

// ---------- карточка товара ----------
$("#pqBtn").onclick = searchProducts;
$("#pq").onkeydown = e => { if (e.key === "Enter") searchProducts(); };
async function searchProducts() {
  const r = await api(`/api/v1/admin/products?q=${encodeURIComponent($("#pq").value)}&per_page=12`);
  $("#plist").innerHTML = r.items.map(p => `<div class="pitem" data-id="${p.id}"><b>${esc(p.name)}</b><div class="muted">${rub(p.price)} / ${esc(p.unit)}</div></div>`).join("") || `<div class="muted">Ничего не найдено</div>`;
  $$(".pitem").forEach(el => el.onclick = () => openProduct(el.dataset.id));
}
async function openProduct(id) {
  const r = await api(`/api/v1/product/${id}`);
  const p = r.product, a = r.annotation;
  const basis = r.calc_basis;
  const inputs = basis === "area" ? `
      <div class="row wrap"><label class="field">Ширина стены, м<input id="cW" type="number" step="0.1" value="3.2"></label>
      <label class="field">Высота стены, м<input id="cH" type="number" step="0.1" value="2.7"></label>
      <label class="field">Проёмы, м²<input id="cO" type="number" step="0.1" value="0"></label></div>
      <div class="muted">или площадь пола:</div>
      <div class="row wrap"><label class="field">Длина комнаты, м<input id="cL" type="number" step="0.1"></label>
      <label class="field">Ширина комнаты, м<input id="cWi" type="number" step="0.1"></label></div>
      <label class="check"><input type="checkbox" id="cDiag"> диагональная укладка</label>`
    : basis === "length" ? `<label class="field">Длина, м<input id="cLen" type="number" step="0.1" value="14"></label>`
    : basis === "points" ? `<label class="field">Электроточек<input id="cPts" type="number" value="10"></label>`
    : `<label class="field">Количество, шт<input id="cCnt" type="number" value="1"></label>`;
  $("#pcard").innerHTML = `<div class="panel card">
    <div><h2>${esc(p.name)}</h2>
      <div class="price">${rub(p.result_price)} <span class="muted">/ ${esc(p.unit)}</span></div>
      ${p.package_area ? `<div class="muted">${p.quantity_in_package ? p.quantity_in_package + " шт в упаковке · " : ""}${p.package_area} м² в упаковке · ${rub(p.price_per_m2)}/м²</div>` : ""}
      <h3>ML-разметка ${a.source === "manual" ? '<span class="chip manual">ручная</span>' : '<span class="chip ml">автоматическая</span>'}</h3>
      <div>${a.work_types.map(w => `<span class="chip ml">${esc(w.name)} ${w.proba != null ? (w.proba * 100).toFixed(0) + "%" : ""}</span>`).join("") || "—"}</div>
      <div class="muted" style="margin-top:6px">Класс материала: <b>${esc(a.kind)}</b> · Помещения: ${a.rooms_named.map(esc).join(", ")}</div>
      <h3>Характеристики</h3>
      <dl class="kv">${(p.characteristics || []).map(c => `<dt>${esc(c.name)}</dt><dd>${esc(c.value)}</dd>`).join("")}</dl>
    </div>
    <div><h3>Сколько нужно?</h3>${inputs}
      <button id="cBtn" style="margin-top:8px">Рассчитать</button>
      <div id="cOut"></div>
      <p class="muted">Этот же расчёт встраивается в любую страницу магазина: <a href="product.html?id=${p.id}" target="_blank">пример карточки с виджетом</a></p>
    </div></div>`;
  $("#cBtn").onclick = async () => {
    const body = {};
    const v = id => { const el = $("#" + id); return el && parseFloat(el.value) > 0 ? parseFloat(el.value) : null; };
    if (basis === "area") {
      if (v("cL") && v("cWi")) { body.length = v("cL"); body.width = v("cWi"); }
      else { body.wall_width = v("cW"); body.wall_height = v("cH"); body.openings_area = v("cO") || 0; }
      body.diagonal = $("#cDiag").checked;
    } else if (basis === "length") body.length = v("cLen");
    else if (basis === "points") body.points = v("cPts");
    else body.count = v("cCnt");
    try {
      const c = await api(`/api/v1/product/${id}/calc`, body);
      $("#cOut").innerHTML = `<div class="total" style="margin-top:12px"><span class="sum">${c.qty} ${esc(c.unit)}</span><span>${rub(c.cost)}</span></div>
        <div class="formula">${esc(c.formula)}</div>${c.assumptions.map(x => `<div class="muted">• ${esc(x)}</div>`).join("")}
        ${c.companions?.length ? `<h3>Понадобится также (${esc(c.work_type.name)})</h3><table>${c.companions.map(x => `<tr><td>${esc(x.product.name)}<div class="formula">${esc(x.formula)}</div></td><td class="num">${x.qty} ${esc(x.unit)}</td><td class="num">${rub(x.cost)}</td></tr>`).join("")}
        <tr><td><b>Итого в корзину</b></td><td></td><td class="num"><b>${rub(c.total_with_companions)}</b></td></tr></table>` : ""}`;
    } catch (e) { $("#cOut").innerHTML = `<div class="warn">${esc(e.message)}</div>`; }
  };
  $("#cBtn").click();
  $("#pcard").scrollIntoView({ behavior: "smooth" });
}

// ---------- админка ----------
async function loadAdmin() {
  const s = await api("/api/v1/admin/stats");
  $("#stats").innerHTML = [
    [s.products, "товаров в каталоге"], [(s.auto_bound_share * 100).toFixed(1) + "%", "отнесены ML к ремонтным работам (остальное — сад, быт, мебель)"],
    [s.manual_bound, "ручных привязок"], [s.low_confidence, "на границе порога → очередь на проверку"],
    [s.timing.last_annotate_ms_per_product + " мс", "разметка одного товара"],
  ].map(([v, l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  if ($("#awt").options.length < 2) META.work_types.forEach(w => $("#awt").add(new Option(w.name, w.id)));
  if (!$("#standUrl").value) $("#standUrl").value = location.origin + "/stand";
  loadAdminList();
}
$("#aBtn").onclick = loadAdminList;
async function loadAdminList() {
  const q = new URLSearchParams({ q: $("#aq").value, work_type: $("#awt").value, source: $("#asrc").value, low_conf: $("#alow").checked, per_page: 40 });
  const r = await api("/api/v1/admin/products?" + q);
  $("#aList").innerHTML = `<div class="muted">Найдено: ${r.total}</div><div class="tablewrap"><table>
    <tr><th>Товар</th><th>Виды работ</th><th>Класс</th><th>Помещения</th><th></th></tr>
    ${r.items.map(p => `<tr data-id="${p.id}"><td>${esc(p.name)}<div class="muted">${esc(p.category)}</div></td>
      <td class="wts">${p.work_types.map(w => `<span class="chip ${p.source}">${esc(w.name)}${w.proba != null && p.source === "ml" ? " " + (w.proba * 100).toFixed(0) + "%" : ""}</span>`).join("") || '<span class="muted">не относится к ремонту</span>'}</td>
      <td>${esc(p.kind)}</td><td class="muted">${p.rooms_named.map(esc).join(", ")}</td>
      <td><button class="ghost edit">Изменить</button></td></tr>`).join("")}</table></div>`;
  $$("#aList .edit").forEach(b => b.onclick = () => editBinding(b.closest("tr")));
}
async function editBinding(tr) {
  const id = tr.dataset.id;
  const p = (await api(`/api/v1/product/${id}`)).annotation;
  const sel = new Set(p.work_types.map(w => w.id));
  const cell = $(".wts", tr);
  cell.innerHTML = META.work_types.map(w => `<span class="chip ${sel.has(w.id) ? "sel ml" : ""}" data-w="${w.id}" style="cursor:pointer">${esc(w.name)}</span>`).join("") +
    `<div class="row" style="margin-top:6px"><button class="save">Сохранить привязку</button>${p.source === "manual" ? '<button class="ghost reset">Вернуть ML</button>' : ""}</div>`;
  $$(".chip", cell).forEach(c => c.onclick = () => { c.classList.toggle("sel"); c.classList.toggle("ml"); });
  $(".save", cell).onclick = async () => {
    await api(`/api/v1/admin/products/${id}/bind`, { work_types: $$(".chip.sel", cell).map(c => c.dataset.w) });
    loadAdmin();
  };
  const reset = $(".reset", cell); if (reset) reset.onclick = async () => { await api(`/api/v1/admin/products/${id}/bind`, undefined, "DELETE"); loadAdmin(); };
}
$("#sRand").onclick = async () => {
  const p = await api("/api/v1/admin/sample-new");
  $("#sName").value = p.name; $("#sCat").value = p.category;
  $("#sDesc").value = [p.description, ...(p.characteristics || []).map(c => `${c.name}: ${c.value}`)].filter(Boolean).join("; ").slice(0, 800);
  $("#sBtn").click();
};
$("#sBtn").onclick = async () => {
  const r = await api("/api/v1/admin/suggest", { name: $("#sName").value, description: $("#sDesc").value, category: $("#sCat").value });
  $("#sOut").innerHTML = `<h3>ML предлагает</h3>
    <div>${r.work_types.map(w => `<span class="chip ml">${esc(w.name)} ${(w.proba * 100).toFixed(0)}%</span>`).join("") || '<span class="muted">не относится к ремонту</span>'}</div>
    <div class="muted" style="margin:6px 0">Класс материала: <b>${esc(r.kind)}</b> (${(r.kind_conf * 100).toFixed(0)}%) · Помещения: ${r.rooms.map(x => esc(x.name)).join(", ")}</div>
    <h3>Топ вероятностей (порог по виду работ)</h3>
    ${r.top.map(t => `<div class="bar"><span>${esc(t.name)}</span><span class="track"><span class="fill" style="width:${t.proba * 100}%"></span></span><span class="v">${(t.proba * 100).toFixed(0)}% / ${(t.threshold * 100).toFixed(0)}%</span></div>`).join("")}
    <h3>Похожие товары каталога</h3>${r.similar.map(s => `<div class="muted">${esc(s.name)} — ${(s.similarity * 100).toFixed(0)}%</div>`).join("")}`;
};
$("#syncBtn").onclick = async () => {
  const b = $("#syncBtn"); b.disabled = true; b.textContent = "Загрузка…";
  try {
    const r = await api("/api/v1/admin/sync", { base_url: $("#standUrl").value, max_products: 500 });
    $("#syncOut").innerHTML = `<p><b>${r.fetched}</b> новых товаров загружено и размечено за ${r.total_s} с (загрузка ${r.fetch_s} с)</p>
      <div class="muted">${r.log.map(esc).join("<br>")}</div>
      <table>${r.items.slice(0, 12).map(i => `<tr><td>${esc(i.name)}</td><td>${i.work_types.map(w => `<span class="chip ml">${esc(w.name)}</span>`).join("") || "—"}</td></tr>`).join("")}</table>`;
    loadAdmin();
  } catch (e) { $("#syncOut").innerHTML = `<div class="warn">${esc(e.message)}</div>`; }
  finally { b.disabled = false; b.textContent = "Синхронизировать"; }
};

// ---------- качество ----------
async function loadQuality() {
  let m;
  try { m = await api("/api/v1/admin/metrics"); } catch (e) { $("#quality").innerHTML = `<div class="warn">${esc(e.message)}</div>`; return; }
  const real = m.dataset.name === "real";
  const grp = real ? "незнакомые категории каталога" : "незнакомые подтипы товаров";
  const names = { random_5fold: `${m.dataset.folds || 5}-fold, случайное разбиение`, group_5fold_unseen_subtypes: `${m.dataset.folds || 5}-fold, ${grp}`, new_products: "новые товары (отложенная выборка)" };
  const f = v => v == null ? "—" : v.toFixed(3);
  const cls = v => v >= 0.8 ? "good" : "bad";
  let rows = "";
  for (const [mode, res] of Object.entries(m.results))
    for (const [p, r] of Object.entries(res)) if (p !== "timing")
      rows += `<tr><td>${mode}</td><td>${names[p]}</td><td class="num ${cls(r.micro_f1)}">${f(r.micro_f1)}</td><td class="num">${f(r.macro_f1)}</td><td class="num">${f(r["ndcg@10"])}</td><td class="num">${f(r.map)}</td><td class="num">${f(r.out_of_scope_correct)}</td><td class="num">${f(r.multi_label_micro_f1)}</td></tr>`;
  const h = m.results.hybrid;
  $("#quality").innerHTML = `<h2>Качество ML-матчинга «товар → виды работ»</h2>
    <p class="muted">${real ? "Реальный каталог Максидома" : "Синтетический каталог"}: ${m.dataset.products.toLocaleString("ru-RU")} товаров, ${m.dataset.work_types} видов работ, ${m.dataset.multi_label_products.toLocaleString("ru-RU")} товаров с несколькими видами работ, ${m.dataset.out_of_scope_products.toLocaleString("ru-RU")} — вне ремонта. Цель: micro-F1 ≥ 0,8.</p>
    <div class="tablewrap"><table><tr><th>Модель</th><th>Протокол</th><th class="num">micro-F1</th><th class="num">macro-F1</th><th class="num">nDCG@10</th><th class="num">MAP</th><th class="num">вне ремонта</th><th class="num">multi-label F1</th></tr>${rows}</table></div>
    ${Object.keys(m.ablation_group).length ? `<h3>Абляция (${grp})</h3>` : ""}
    ${Object.keys(m.ablation_group).length ? `<table><tr><th>Вариант</th><th class="num">micro-F1</th><th class="num">macro-F1</th><th class="num">nDCG@10</th></tr>` : "<table>"}
    ${Object.entries(m.ablation_group).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${f(v.micro_f1)}</td><td class="num">${f(v.macro_f1)}</td><td class="num">${f(v["ndcg@10"])}</td></tr>`).join("")}</table>
    <h3>F1 по видам работ (hybrid)</h3>
    <div class="tablewrap"><table><tr><th>Вид работ</th><th class="num">товаров</th><th class="num">случайное</th><th class="num">${grp}</th><th class="num">новые товары</th></tr>
    ${m.classes.map((c, i) => `<tr><td>${esc(wtName(c))}</td><td class="num">${h.random_5fold.support[i]}</td><td class="num">${f(h.random_5fold.per_class_f1[i])}</td><td class="num">${f(h.group_5fold_unseen_subtypes.per_class_f1[i])}</td><td class="num">${f(h.new_products.per_class_f1[i])}</td></tr>`).join("")}</table></div>
    <h3>Производительность</h3>
    <div class="muted">hybrid: обучение ${h.timing.train_s} с, инференс ${h.timing.predict_ms_per_product} мс/товар; эмбеддинги каталога ${m.resources.embed_time_s_all_products} с; пиковая память ${m.resources.peak_rss_mb} МБ; ${esc(m.resources.hardware)}</div>`;
}

// ---------- старт ----------
(async () => {
  META = await api("/api/v1/meta");
  const h = await api("/health");
  $("#health").textContent = `${h.dataset === "real" ? "каталог Максидома" : "синтетический каталог"} · ${h.products.toLocaleString("ru-RU")} товаров · модель ${h.model} · эмбеддинги ${h.embeddings ? "✓" : "✗"} · LLM ${h.llm ? "✓" : "выкл"}`;
  addRoom({ type: "bathroom", area: 6, humidity: "high" });
  addRoom({ type: "kitchen", length: 3, width: 4 });
  searchProducts();
})();
