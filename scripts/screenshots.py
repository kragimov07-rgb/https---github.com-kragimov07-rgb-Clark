"""Скриншоты интерфейса для презентации (docs/img). Сервис должен быть запущен на localhost:8000.

Запуск: PLAYWRIGHT_BROWSERS_PATH=.venv/pw python scripts/screenshots.py [out_dir]
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"{BASE}/ui/")
        pg.wait_for_timeout(1500)
        pg.click("#demo1")
        pg.wait_for_selector(".sum", timeout=60000)
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out / "1_calc.png"))

        pg.click("text=Карточка товара")
        pg.wait_for_selector(".pitem", timeout=30000)
        pg.click(".pitem >> nth=0")
        pg.wait_for_selector("#cOut .sum", timeout=30000)
        pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('#pcard').scrollIntoView()")
        pg.screenshot(path=str(out / "2_product.png"))
        pid = pg.evaluate("document.querySelector('#pcard a[href*=product]').href.split('id=')[1]")

        pg.click("text=Админка")
        pg.wait_for_selector(".stat", timeout=30000)
        pg.click("#sRand")
        pg.wait_for_selector("#sOut .bar", timeout=30000)
        pg.click("#syncBtn")
        pg.wait_for_selector("#syncOut table", timeout=180000)
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out / "3_admin.png"))

        pg.click("text=Качество ML")
        try:  # отчёт метрик может быть ещё не сформирован
            pg.wait_for_selector("#quality table", timeout=10000)
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(out / "5_quality.png"), full_page=True)
        except Exception:
            print("нет отчёта метрик — скриншот качества пропущен")

        w = b.new_page(viewport={"width": 1100, "height": 800})
        w.on("pageerror", lambda e: errors.append(str(e)))
        w.goto(f"{BASE}/ui/product.html?id={pid}")
        w.wait_for_selector(".rcw button", timeout=30000)
        w.click(".rcw button")
        w.wait_for_selector(".rcw .big", timeout=30000)
        w.screenshot(path=str(out / "4_widget.png"))

        m = b.new_page(viewport={"width": 400, "height": 860})
        m.on("pageerror", lambda e: errors.append(str(e)))
        m.goto(f"{BASE}/ui/")
        m.wait_for_timeout(1200)
        m.click("#calcBtn")
        m.wait_for_selector(".sum", timeout=60000)
        print("mobile scrollWidth", m.evaluate("document.documentElement.scrollWidth"))
        b.close()
    print("errors:", errors)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "docs" / "img")
