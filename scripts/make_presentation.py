"""Презентация для защиты: docs/RepairCalc.pptx. Цифры берутся из reports/metrics_<набор>.json и живого сервиса.

Запуск: python -m scripts.make_presentation
"""
import json
import sys
import time
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GREEN = RGBColor(0x1F, 0x8A, 0x4C)
DARK = RGBColor(0x1D, 0x23, 0x30)
MUTED = RGBColor(0x6B, 0x73, 0x85)
LIGHT = RGBColor(0xE8, 0xF5, 0xED)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
W, H = Emu(12192000), Emu(6858000)  # 16:9
IMG = ROOT / "docs" / "img"


def cm(x):
    return Emu(int(x * 360000))


class Deck:
    def __init__(self):
        self.p = Presentation()
        self.p.slide_width, self.p.slide_height = W, H
        self.n = 0

    def slide(self, title, notes="", kicker=None):
        s = self.p.slides.add_slide(self.p.slide_layouts[6])
        self.n += 1
        bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, cm(0.35), H)
        bar.fill.solid(); bar.fill.fore_color.rgb = GREEN; bar.line.fill.background()
        if kicker:
            self.text(s, kicker, 1.5, 0.8, 30, 0.8, 12, MUTED)
        self.text(s, title, 1.5, 1.3, 30, 1.6, 28, DARK, bold=True)
        self.text(s, f"RepairCalc · {self.n}", 28.5, 18, 5, 0.6, 10, MUTED, align=PP_ALIGN.RIGHT)
        if notes:
            s.notes_slide.notes_text_frame.text = notes
        return s

    def text(self, s, txt, x, y, w, h, size=16, color=DARK, bold=False, align=None):
        tb = s.shapes.add_textbox(cm(x), cm(y), cm(w), cm(h))
        tf = tb.text_frame
        tf.word_wrap = True
        lines = txt if isinstance(txt, list) else [txt]
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = para.add_run()
            run.text = line
            run.font.size = Pt(size)
            run.font.color.rgb = color
            run.font.bold = bold
            if align:
                para.alignment = align
            para.space_after = Pt(6)
        return tb

    def bullets(self, s, items, x=1.5, y=3.4, w=30, size=17):
        return self.text(s, [f"•  {i}" for i in items], x, y, w, 14, size)

    def card(self, s, x, y, w, h, big, small, fill=LIGHT):
        r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, cm(x), cm(y), cm(w), cm(h))
        r.fill.solid(); r.fill.fore_color.rgb = fill; r.line.fill.background()
        r.adjustments[0] = 0.08
        self.text(s, big, x + 0.4, y + 0.3, w - 0.8, 1.4, 26, GREEN, bold=True)
        self.text(s, small, x + 0.4, y + 1.7, w - 0.8, h - 1.8, 13, DARK)

    def table(self, s, rows, x, y, w, col_w=None, size=12, header=True):
        t = s.shapes.add_table(len(rows), len(rows[0]), cm(x), cm(y), cm(w), cm(0.8 * len(rows))).table
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                c = t.cell(i, j)
                c.text = str(val) or " "
                para = c.text_frame.paragraphs[0]
                para.runs[0].font.size = Pt(size)
                para.runs[0].font.bold = header and i == 0
                para.runs[0].font.color.rgb = WHITE if (header and i == 0) else DARK
                c.fill.solid()
                c.fill.fore_color.rgb = GREEN if (header and i == 0) else (LIGHT if i % 2 == 0 else WHITE)
        if col_w:
            for j, cw in enumerate(col_w):
                t.columns[j].width = cm(cw)
        return t

    def image(self, s, name, x, y, w=None, h=None):
        f = IMG / name
        if f.exists():
            s.shapes.add_picture(str(f), cm(x), cm(y), cm(w) if w else None, cm(h) if h else None)


def main():
    from app.calc.estimate import estimate
    from app.config import DATASET
    from app.service import get_index

    m = json.loads((ROOT / "reports" / f"metrics_{DATASET}.json").read_text())
    syn = json.loads((ROOT / "reports" / "metrics_synthetic.json").read_text())
    hyb, base = m["results"]["hybrid"], m["results"]["baseline"]
    ds = m["dataset"]
    t0 = time.perf_counter()
    idx = get_index()
    start_s = time.perf_counter() - t0
    prods = list(idx.catalog)
    in_scope = sum(1 for p in prods if p["_wt"])
    demo = estimate(idx, "apartment", "capital", [{"type": "bathroom", "area": 6, "humidity": "high"}])
    f = lambda v: f"{v:.3f}".replace(".", ",")  # noqa: E731
    num = lambda v: f"{v:,}".replace(",", " ")  # noqa: E731
    gs, nw, rnd = hyb["group_5fold_unseen_subtypes"], hyb["new_products"], hyb["random_5fold"]
    bgs = base["group_5fold_unseen_subtypes"]

    d = Deck()
    # 1
    s = d.slide("RepairCalc", kicker="SpbTechRun 2026 · кейс №1 · Максидом")
    d.text(s, "Микросервис умных калькуляторов ремонта: ML-подбор материалов под помещение и точный расчёт "
              "количества и стоимости по реальному каталогу Максидома", 1.5, 3.4, 26, 3, 20, DARK)
    d.text(s, "Команда «___» · капитан ___", 1.5, 15.5, 20, 1, 14, MUTED)
    d.image(s, "1_calc.png", 18, 7, w=15)

    # 2
    s = d.slide("Проблема: покупатель не знает, сколько и что купить", kicker="Боль",
                notes="Пользователь не понимает объём материалов и бюджет — бросает корзину, звонит в поддержку.")
    d.bullets(s, ["Сколько упаковок плитки на стену 3,2 × 2,7? Какой клей и сколько затирки?",
                  "Что можно в санузел, а что нельзя: обычный ГКЛ или ГКЛВ, какая краска, какие розетки?",
                  "Итог — брошенные корзины, звонки менеджерам, низкая конверсия «под задачу»",
                  "Готовые калькуляторы статичны: не учитывают влажность и назначение комнаты,",
                  "не привязаны к каталогу и остаткам и не масштабируются на десятки тысяч SKU без ручной настройки"])

    # 3
    s = d.slide("Решение: три сценария на одном движке", kicker="Продукт",
                notes="Все три сценария используют общий движок: ML-разметка каталога + планировщик работ + формулы расхода.")
    d.card(s, 1.5, 3.6, 10, 6, "Смета", ["Квартира / студия / дом,", "косметический / капитальный /", "дизайнерский ремонт,",
                                          "помещения → товары, количество, итог"])
    d.card(s, 12.2, 3.6, 10, 6, "Комната", ["Влажность, назначение, нагрузка", "→ влагостойкие, моющиеся,", "износостойкие материалы",
                                            "+ пояснение «почему» (RAG)"])
    d.card(s, 22.9, 3.6, 10, 6, "Карточка", ["/api/v1/product/{id}/calc", "размеры стены → упаковки и цена", "+ клей, затирка, грунт", "одной кнопкой в корзину"])
    d.text(s, f"В основе — ML, который сам относит {num(len(prods))} товаров каталога к 26 видам работ, классам материалов и помещениям",
           1.5, 11, 31, 2, 17, GREEN, bold=True)

    # 4
    s = d.slide("Данные: реальный каталог Максидома", kicker="Данные",
                notes="Выгрузка организаторов + YML-фид из вики хакатона. Соединение по коду товара в URL оффера. Разметка на уровне категорий — как работала бы админка магазина.")
    d.card(s, 1.5, 3.6, 7.5, 5, "88 790", ["карточек из выгрузки", "организаторов"])
    d.card(s, 9.6, 3.6, 7.5, 5, "56 555", ["присоединены к YML-фиду:", "цена СПб, наличие, фото"])
    d.card(s, 17.7, 3.6, 7.5, 5, "1 083", ["ремонтные категории", "размечены вручную"])
    d.card(s, 25.8, 3.6, 7.5, 5, f"{num(ds['products'] - ds['out_of_scope_products'])}", ["товаров относятся", "к ремонту (≈ 35%)"])
    d.bullets(s, ["Дерево категорий восстановлено по фиду (2 360 из 2 375 категорий)",
                  "Характеристики без единиц: «Вес 5000» (г) и «Вес 5» (кг), «Расход 2,1-5,2», «Литраж .9», размеры в мм",
                  "→ нормализация: диапазоны, единицы по правдоподобию, отрицания «не влагостойкие», данные из названия",
                  "65% ассортимента — не ремонт (сад, посуда, мебель): модель должна не навязывать им виды работ",
                  f"{num(ds['multi_label_products'])} товаров относятся сразу к нескольким видам работ"], y=9.6, size=15)

    # 5
    s = d.slide(f"Демо: санузел 6 м², капремонт → {float(demo['total']):,.0f} ₽".replace(",", " "), kicker="Сценарий 1",
                notes="Реальные товары Максидома: ГКЛВ, гидроизоляция с заведением на стены, плитка с подрезкой, IP44, вентилятор, тёплый пол, смесители, унитаз; формула у каждой позиции.")
    d.image(s, "1_calc.png", 1.5, 3.3, h=14)
    d.bullets(s, [f"{demo['lines_count']} позиций за {demo['elapsed_ms']:.0f} мс",
                  "Реальные товары и цены СПб",
                  "Только влагостойкие материалы, IP44",
                  "Гидроизоляция + 30 см на стены",
                  "Формула у каждой позиции",
                  "Альтернативы и «почему»"], x=22, y=3.6, w=11.5, size=14)

    # 6
    s = d.slide("Расчёт прямо в карточке товара", kicker="Сценарий 3",
                notes="Виджет встраивается в любую страницу (в т.ч. Bitrix) двумя строками. Сопутствующие товары — того же вида работ, с выбором выгодной фасовки.")
    d.image(s, "2_product.png", 1.5, 3.3, h=13.5)
    d.image(s, "4_widget.png", 21.5, 3.3, w=12)
    d.text(s, ["<div data-repaircalc-product=\"ID\"></div>", "<script src=\"…/ui/widget.js\"></script>"], 21.5, 12.6, 12, 2, 11, MUTED)

    # 7
    s = d.slide("ML-матчинг «товар → виды работ»", kicker="Где ML",
                notes="Гибрид: логрегрессия точна на знакомых категориях; zero-shot по справочнику и kNN по эмбеддингам переносят знание на новые; шлюз отсекает товары вне ремонта.")
    d.table(s, [["Компонент", "Что даёт"],
                ["TF-IDF слов и символов + логрегрессия OvR", "точность на знакомых категориях"],
                ["Эмбеддинги multilingual-e5 (локально, MIT)", "смысл, а не буквальные совпадения"],
                ["Zero-shot: сходство с типовыми материалами каждого вида работ", "новые категории без обучения"],
                ["kNN по размеченным товарам", "перенос разметки похожих товаров"],
                ["Шлюз «относится к ремонту»", "сад, посуда, мебель → без меток"],
                ["Пороги по каждому виду работ (out-of-fold)", "баланс точности и полноты"],
                ["Второй классификатор: класс материала (48 классов)", "выбор формулы расхода"]],
            1.5, 3.4, 31, col_w=[18, 13], size=13)
    d.text(s, "Админка: ручная привязка важнее ML; товары «на границе порога» — в очередь на проверку", 1.5, 11.2, 31, 1, 15, GREEN, bold=True)

    # 8
    s = d.slide("Справочник: 26 видов работ, 5 этапов, 7 правил разметки", kicker="Таксономия",
                notes="Таксономия по технологической последовательности. Правила R1–R7 и разбор неоднозначных товаров — docs/taxonomy.md, перенос на категории каталога — docs/real_data.md.")
    d.bullets(s, ["Подготовка → черновые → инженерные системы → чистовая отделка → завершающие",
                  "Вид работ = законченная технологическая операция: «укладка плитки», «монтаж ГКЛ»",
                  "Товар → все работы, где он основной материал, расходник или специализированный инструмент",
                  "Неоднозначные: грунтовка (6 работ), монтажная пена, обои под покраску, полотенцесушитель, дюбели",
                  "Вне охвата: кладка, фасад, кровля, сад, быт → пустой набор меток",
                  "Каждый вид работ связан с формулами калькулятора — разметка сразу работает в смете",
                  "Эталон: категория → виды работ + уточняющие правила по названию для смешанных категорий"])

    # 9
    s = d.slide("Качество на реальном каталоге: micro-F1 ≥ 0,8", kicker="Метрики",
                notes="Основной сценарий — новые товары в известных категориях: 0,97. Самый жёсткий протокол — незнакомые категории: модель не видела ни одного товара категории; гибрид лучше baseline на всех метриках.")
    d.table(s, [["Протокол", "micro-F1", "macro-F1", "nDCG@10", "вне ремонта", "multi-label"],
                [f"{ds.get('folds', 3)}-fold по товарам", f(rnd["micro_f1"]), f(rnd["macro_f1"]), f(rnd["ndcg@10"]), f(rnd["out_of_scope_correct"]), f(rnd["multi_label_micro_f1"])],
                ["Новые товары (отложенные 3%)", f(nw["micro_f1"]), f(nw["macro_f1"]), f(nw["ndcg@10"]), f(nw["out_of_scope_correct"]), f(nw["multi_label_micro_f1"])],
                ["Незнакомые категории — hybrid", f(gs["micro_f1"]), f(gs["macro_f1"]), f(gs["ndcg@10"]), f(gs["out_of_scope_correct"]), f(gs["multi_label_micro_f1"])],
                ["Незнакомые категории — baseline", f(bgs["micro_f1"]), f(bgs["macro_f1"]), f(bgs["ndcg@10"]), f(bgs["out_of_scope_correct"]), f(bgs["multi_label_micro_f1"])]],
            1.5, 3.4, 31, col_w=[11, 4, 4, 4, 4, 4], size=14)
    d.text(s, [f"{num(ds['products'])} товаров, 26 видов работ. На незнакомых категориях гибрид vs baseline: "
               f"micro-F1 +{(gs['micro_f1'] - bgs['micro_f1']) * 100:.1f} п.п., macro-F1 +{(gs['macro_f1'] - bgs['macro_f1']) * 100:.1f} п.п., "
               f"nDCG@10 +{(gs['ndcg@10'] - bgs['ndcg@10']) * 100:.1f} п.п.",
               "Всё воспроизводится: python -m eval.evaluate (отчёт reports/metrics_real.md)"], 1.5, 9.4, 31, 2.5, 14, MUTED)

    # 10
    pc = {c: (gs["per_class_f1"][i], rnd["per_class_f1"][i]) for i, c in enumerate(m["classes"])}
    from app.taxonomy import work_type_name
    strong = sorted(pc, key=lambda c: -pc[c][0])[:5]
    weak = sorted(pc, key=lambda c: pc[c][0])[:5]
    s = d.slide("Где модель сильна и где растём", kicker="Честно о качестве",
                notes="Слабые на незнакомых категориях — виды работ, которые в каталоге представлены 1–2 непохожими категориями. План: доразметка, LLM для товаров на границе порога, расширение справочника.")
    d.table(s, [["Сильные (F1, незнакомые категории)", ""]] + [[work_type_name(c), f(pc[c][0])] for c in strong], 1.5, 3.4, 15, col_w=[11, 4], size=13)
    d.table(s, [["Растём (F1, незнакомые категории)", "по товарам"]] + [[work_type_name(c), f"{f(pc[c][0])} / {f(pc[c][1])}"] for c in weak],
            17.5, 3.4, 16, col_w=[10, 6], size=13)
    d.bullets(s, ["На знакомых категориях все виды работ ≥ 0,89 F1",
                  "Очередь «на границе порога» в админке → локальная LLM / проверка человеком",
                  "Синтетический стенд с абляцией: без zero-shot компонента micro-F1 на новых подтипах падает с "
                  f"{f(syn['results']['hybrid']['group_5fold_unseen_subtypes']['micro_f1'])} до {f(syn['ablation_group']['без zero-shot вероятности']['micro_f1'])}"],
              y=9.6, size=15)

    # 11
    s = d.slide("Математическая модель расчёта", kicker="Формулы",
                notes="Каждая позиция показывает формулу. 16 эталонных расчётов вручную — MAE = 0 (tests/test_formulas.py). Расход берётся из карточки, если правдоподобен; иначе норма с пометкой.")
    d.table(s, [["Материал", "Формула"],
                ["Плитка, ламинат, SPC", "⌈S · (1 + запас) / S упаковки⌉; запас 10% / 15% диагональ / +5% при S < 4 м²"],
                ["Обои", "полосы = ⌈L стен / ширина⌉; в рулоне = ⌊длина / (h + раппорт + 0,1)⌋; рулоны = ⌈полосы / в рулоне⌉"],
                ["Краска, грунт", "⌈S · расход л/м² · слои / объём⌉; краска в кг — через плотность 1,4 кг/л"],
                ["Смеси (клей, штукатурка, шпаклёвка, стяжка, наливной пол)", "⌈S · расход кг/м²·мм · толщина / вес мешка⌉"],
                ["Гидроизоляция", "(S пола + P · 0,3 м) · расход · 2 слоя; «1200» в карточке → 1,2 кг/м²"],
                ["Линолеум", "полосы по ширине рулона × (длина + 0,1 м)"],
                ["Электрика", "кабель = точки · 7 м + 10 м → бухты по «Метраж упаковки»"]],
            1.5, 3.4, 31, col_w=[10, 21], size=12)
    d.text(s, "Учёт единицы продажи (уп., рул., кв.м, шт.); деньги в Decimal; цена — по фиду СПб; MAE на эталонных расчётах = 0",
           1.5, 11.3, 31, 2, 14, GREEN, bold=True)

    # 12
    s = d.slide("Подбор под помещение и выгодная фасовка", kicker="Рекомендации",
                notes="Фильтр позиции по названию защищает от ошибок ML (мешки для пылесоса вместо строительных). Выбор с учётом итоговой стоимости позиции — мешок 20 кг вместо 14 банок по 1,5 кг.")
    d.bullets(s, ["Кандидаты: ML (или админка) отнёс товар к виду работ и классу материала",
                  "Фильтр позиции по названию: «смеситель для раковины», «плинтус», «подрозетник» — защита от ошибок ML",
                  "Жёсткие ограничения: санузел → влагостойкие и IP44; балкон → цементные смеси; кухня, прихожая → ламинат ≥ 33",
                  "Ранжирование: уверенность ML, соответствие позиции, наличие в фиде, ценовой сегмент по цене за кг/л/м²",
                  "Выбор: качество − штраф за переплату → выгодная фасовка (мешок 20 кг, а не 14 банок по 1,5 кг)",
                  "Пояснение RAG: база норм и требований к помещениям + локальная LLM (без неё — шаблон)"], size=16)

    # 13
    s = d.slide("Полный цикл: загрузка каталога → авторазметка → админка", kicker="Админка",
                notes="Синхронизация обходит дерево категорий, читает страницы до last_page, дочитывает полные карточки и размечает товары.")
    d.image(s, "3_admin.png", 1.5, 3.3, h=13.5)
    d.bullets(s, [f"{num(in_scope)} из {num(len(prods))} товаров ML отнёс к ремонту",
                  "500 новых товаров со стенда: загрузка и разметка ≈ 3 с",
                  "Реальный товар, которого модель не видела → виды работ, класс, помещения",
                  "Ручная привязка важнее ML, откат в один клик",
                  "Очередь «на границе порога»"], x=21.5, y=3.6, w=12, size=14)

    # 14
    r = m["resources"]
    s = d.slide("Производительность и закрытый контур", kicker="Инфраструктура",
                notes="Все модели локальные. На сервере заказчика RTX 3090 отдаётся под LLM, эмбеддинги работают на CPU.")
    d.card(s, 1.5, 3.6, 7.5, 5, f"{hyb['timing']['predict_ms_per_product']:.0f} мс", ["ML-разметка товара"])
    d.card(s, 9.6, 3.6, 7.5, 5, f"{demo['elapsed_ms']:.0f} мс", ["смета на санузел", f"({demo['lines_count']} позиций)"])
    d.card(s, 17.7, 3.6, 7.5, 5, f"{hyb['timing']['train_s'] / 60:.1f} мин".replace(".", ","), ["обучение модели", "на 86 тыс. товаров"])
    d.card(s, 25.8, 3.6, 7.5, 5, f"{start_s:.0f} с", ["старт сервиса", "(кэш разметки)"])
    d.bullets(s, ["Эмбеддинги multilingual-e5-small (MIT), 470 МБ, CPU/MPS; LLM: Ollama + Qwen2.5 (Apache-2.0) на RTX 3090",
                  "Без LLM всё работает: разбор текста и пояснения — на правилах и шаблонах",
                  f"Память сервиса ≈ 3 ГБ на весь каталог; пиковая при обучении ≈ {r['peak_rss_mb'] / 1024:.0f} ГБ; Docker + docker-compose",
                  "Лицензии проверены скриптом: GPL/AGPL нет (make licenses)"], y=9.6, size=15)

    # 15
    s = d.slide("Ценность и развитие", kicker="Бизнес",
                notes="Метрики эффекта для пилота: конверсия карточки в корзину, средний чек, доля корзин «под задачу», нагрузка на поддержку.")
    d.bullets(s, ["Рост конверсии и среднего чека: продажа «под задачу», сопутствующие товары одной кнопкой",
                  "Меньше ручной работы: 2 375 категорий вместо 88 тыс. SKU; новые товары размечаются автоматически",
                  "Меньше звонков в поддержку: смета и пояснения прямо на сайте",
                  "Пилот: A/B на карточках плитки, ламината и обоев; метрики — CR в корзину, средний чек, время до корзины",
                  "Развитие: данные заказов → обучаемые коэффициенты отходов; LLM для товаров на границе порога;",
                  "CV по плану квартиры; новые вертикали (сад, инструмент) = новый справочник + make train"])

    # 16
    s = d.slide("Спасибо! Живое демо", kicker="RepairCalc")
    d.bullets(s, ["UI: /ui/  ·  Swagger: /docs  ·  метрики: вкладка «Качество ML»",
                  "Код, справочник, разметка категорий, методика, отчёты — в репозитории",
                  "make setup model real-data train run — воспроизводится с нуля"], size=18)
    d.image(s, "5_quality.png", 21, 6.5, h=11)

    out = ROOT / "docs" / "RepairCalc.pptx"
    d.p.save(out)
    print(f"{d.n} слайдов -> {out}")


if __name__ == "__main__":
    main()
