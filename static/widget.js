/* RepairCalc widget: расчёт количества товара прямо в карточке.
 * Встраивание (Bitrix, любой сайт):
 *   <div data-repaircalc-product="96611"></div>
 *   <script src="https://<repaircalc-host>/ui/widget.js" defer></script>
 */
(function () {
  const script = document.currentScript;
  const API = script ? new URL(script.src).origin : location.origin;
  const css = `
  .rcw,.rcw *{box-sizing:border-box}.rcw{font:14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;border:1px solid #d9dee6;border-radius:10px;padding:14px;max-width:420px;background:#fff;color:#1d2330}
  .rcw h4{margin:0 0 8px;font-size:15px}.rcw .r{display:flex;gap:8px;margin-bottom:8px}
  .rcw input{width:100%;padding:7px;border:1px solid #d9dee6;border-radius:8px;font:inherit}
  .rcw label{flex:1;font-size:12px;color:#6b7385;display:flex;flex-direction:column;gap:3px}
  .rcw button{background:#1f8a4c;color:#fff;border:0;border-radius:8px;padding:9px 14px;font:inherit;cursor:pointer;width:100%}
  .rcw .res{margin-top:10px}.rcw .big{font-size:20px;font-weight:700}.rcw .f{font-size:11.5px;color:#6b7385}
  .rcw table{width:100%;font-size:12.5px;border-collapse:collapse;margin-top:6px}.rcw td{padding:4px 0;border-top:1px solid #eef0f4}
  .rcw td:last-child{text-align:right;white-space:nowrap}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  const rub = v => Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 0 }) + " ₽";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function mount(el) {
    const id = el.dataset.repaircalcProduct;
    let info;
    try { info = await (await fetch(`${API}/api/v1/product/${id}`)).json(); } catch { return; }
    const basis = info.calc_basis;
    if (basis !== "area" && basis !== "length") return; // для штучных товаров виджет не нужен
    el.innerHTML = `<div class="rcw"><h4>Рассчитать количество</h4>
      ${basis === "area" ? `<div class="r"><label>Длина, м<input class="l" type="number" step="0.1" value="3"></label>
        <label>Ширина / высота, м<input class="w" type="number" step="0.1" value="2.7"></label></div>`
        : `<div class="r"><label>Длина, м<input class="l" type="number" step="0.1" value="12"></label></div>`}
      <button>Рассчитать</button><div class="res"></div></div>`;
    const box = el.querySelector(".rcw");
    box.querySelector("button").onclick = async () => {
      const l = parseFloat(box.querySelector(".l").value), w = parseFloat(box.querySelector(".w")?.value);
      const body = basis === "area" ? { area: l * w } : { length: l };
      const r = await (await fetch(`${API}/api/v1/product/${id}/calc`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json();
      box.querySelector(".res").innerHTML = r.qty === undefined ? `<div class="f">${esc(r.detail)}</div>` : `
        <div class="big">${r.qty} ${esc(r.unit)} · ${rub(r.cost)}</div><div class="f">${esc(r.formula)}</div>
        ${r.companions?.length ? `<table>${r.companions.map(c => `<tr><td>${esc(c.product.name)}</td><td>${c.qty} ${esc(c.unit)} · ${rub(c.cost)}</td></tr>`).join("")}
        <tr><td><b>Всё для работы</b></td><td><b>${rub(r.total_with_companions)}</b></td></tr></table>` : ""}`;
    };
  }
  const run = () => document.querySelectorAll("[data-repaircalc-product]").forEach(mount);
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", run) : run();
})();
