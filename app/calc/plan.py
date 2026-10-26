"""План работ: какие виды работ и материалы нужны помещению при данном типе объекта и ремонта.

Геометрия: площадь пола, периметр (из длины/ширины или из площади для квадратной комнаты),
площадь стен = периметр × высота − проёмы.
"""
import math
from dataclasses import dataclass, field

DOOR_W, DOOR_H = 0.8, 2.0
WINDOW_W, WINDOW_H = 1.2, 1.4


@dataclass
class Room:
    type: str
    area: float | None = None
    length: float | None = None
    width: float | None = None
    height: float = 2.7
    doors: int | None = None
    windows: int | None = None
    name: str | None = None
    wall_finish: str | None = None  # paint | wallpaper | tile | panels | decor
    floor_finish: str | None = None  # laminate | tile | linoleum | spc
    humidity: str | None = None  # low | medium | high — переопределяет справочник

    def __post_init__(self):
        if self.length and self.width and not self.area:
            self.area = self.length * self.width
        if self.doors is None:
            self.doors = 1
        if self.windows is None:
            self.windows = 0 if self.type in ("bathroom", "toilet", "hallway") else 1

    @property
    def perimeter(self) -> float:
        if self.length and self.width:
            return 2 * (self.length + self.width)
        return 4 * math.sqrt(self.area)

    @property
    def openings_area(self) -> float:
        return self.doors * DOOR_W * DOOR_H + self.windows * WINDOW_W * WINDOW_H

    @property
    def wall_area(self) -> float:
        return max(self.perimeter * self.height - self.openings_area, 0)

    @property
    def wall_length_for_wallpaper(self) -> float:
        return max(self.perimeter - self.doors * DOOR_W, 0)

    @property
    def skirting_length(self) -> float:
        return max(self.perimeter - self.doors * DOOR_W, 0)


@dataclass
class Slot:
    """Позиция сметы: вид работ + класс материала + база расчёта + требования к товару."""
    work_type: str
    kind: str
    basis: float
    surface: str  # floor | walls | ceiling | room
    title: str
    prefer: list = field(default_factory=list)  # ключевые слова — бонус при ранжировании
    require: dict = field(default_factory=dict)  # жёсткие требования: moisture_resistant, wear_class_min...
    ctx: dict = field(default_factory=dict)
    optional: bool = False
    must: str | None = None  # регэксп по названию: товар обязан ему соответствовать (если такие есть)


WET = {"bathroom", "toilet"}


def room_profile(room: Room, taxonomy_rooms: dict) -> dict:
    prof = dict(taxonomy_rooms.get(room.type, {}))
    if room.humidity:
        prof["humidity"] = room.humidity
    return prof


def default_finishes(room: Room, repair: str):
    wall = room.wall_finish
    floor = room.floor_finish
    t = room.type
    if not wall:
        wall = {"bathroom": "tile", "toilet": "tile", "kitchen": "paint", "hallway": "paint",
                "balcony": "panels"}.get(t, "wallpaper")
        if repair == "cosmetic" and t in WET:
            wall = "paint"
        if repair == "designer" and t in ("living", "bedroom"):
            wall = "paint"
    if not floor:
        floor = {"bathroom": "tile", "toilet": "tile", "kitchen": "tile", "hallway": "tile", "balcony": "tile"}.get(t, "laminate")
        if repair == "cosmetic" and t in ("kitchen", "hallway"):
            floor = "spc"
    return wall, floor


def requirements(room: Room, prof: dict) -> dict:
    req = {}
    if prof.get("humidity") == "high" or room.type in WET:
        req["moisture_resistant"] = True
    if prof.get("cold"):
        req["frost_resistant"] = True
    return req


def plan_room(room: Room, object_type: str, repair: str, prof: dict) -> list[Slot]:
    S = []
    floor, walls, ceil = room.area, room.wall_area, room.area
    wet = room.type in WET or prof.get("humidity") == "high"
    req = requirements(room, prof)
    wall_fin, floor_fin = default_finishes(room, repair)
    capital = repair in ("capital", "designer")
    geo = {"height": room.height, "wall_length": room.wall_length_for_wallpaper, "length": room.length, "width": room.width}

    def add(wt, kind, basis, surface, title, prefer=(), require=None, ctx=None, optional=False, must=None):
        if basis and basis > 0:
            S.append(Slot(wt, kind, round(basis, 3), surface, title, list(prefer), require or {}, {**geo, **(ctx or {})},
                          optional, must))

    # --- подготовка и черновые ---
    if capital:
        add("demolition", "tool", 1, "room", "Мешки для строительного мусора", ["мешк"], optional=True, must=r"мешок для строительного мусора|мешк\w* для строительного мусора")
        add("priming", "primer", floor + walls, "room", "Грунтовка стен и пола", ["глубок"], must=r"глубок")
        if wall_fin != "tile":
            add("plastering", "plaster_mix", walls, "walls", "Штукатурка стен",
                ["цемент"] if (wet or prof.get("cold")) else ["гипс"], ctx={"plaster_mm": 15},
                must=r"цемент" if (wet or prof.get("cold")) else None)
            add("plastering", "consumable", math.ceil(room.perimeter / 1.5), "walls", "Штукатурные маяки", ["маяк"],
                optional=True, must=r"^маяк")
        add("screed", "screed_mix", floor, "floor", "Стяжка пола", ["стяжк", "пескобетон"], ctx={"screed_mm": 40})
        add("screed", "consumable", math.ceil(room.perimeter / 25), "floor", "Демпферная лента", ["демпфер", "кромоч"],
            optional=True, must=r"демпфер|кромочн")
        if floor_fin in ("laminate", "linoleum", "spc"):
            add("self_leveling", "self_leveling_mix", floor, "floor", "Наливной пол (финишное выравнивание)")
        if wet:
            wp_area = floor + room.perimeter * 0.3
            add("waterproofing", "waterproofing_mix", wp_area, "floor", "Гидроизоляция пола и примыканий",
                ["обмазоч", "полимер"], must=r"^(?!.*(битум|кровел)).*(гидроизол|мастик)")
            add("waterproofing", "waterproofing_tape", room.perimeter + 2, "floor", "Гидроизоляционная лента в углы",
                ["угл", "лента"], must=r"лент")
            add("drywall", "drywall_sheet", 2.5, "walls", "Короб для труб из ГКЛВ", ["гклв", "влагост"],
                require={"moisture_resistant": True})
            add("drywall", "profile", 2.5, "walls", "Профиль для короба", ["пп", "пн", "60х27", "27х28"], must=r"^профиль (потолочн|направляющ|стоечн|пп|пн|пс)")
        if prof.get("cold") or object_type == "house" and room.type == "balcony":
            add("insulation", "insulation_board", walls + floor, "walls", "Утепление балкона", ["xps", "50мм", "100мм", "x50", "х50"],
                require={})
            add("insulation", "consumable", 1, "walls", "Пароизоляция", ["пароизоляц"], optional=True, must=r"пароизол|мембран")

    # --- инженерные системы ---
    sockets = max(2, math.ceil(room.area / 5)) + (3 if room.type == "kitchen" else 0)
    lights = 1 if room.area < 10 else 2
    if repair == "designer":
        lights += math.ceil(room.area / 3)
    if capital:
        points = sockets + lights + 1
        add("electrical_wiring", "cable", points, "room", "Кабель для проводки", ["3x2,5", "3х2,5", "ввг"],
            must=r"ввг.*3\s?[хx]\s?(1,5|2,5)")
        add("electrical_wiring", "conduit", points, "room", "Гофротруба", ["гофр", "16мм", "20мм"], must=r"^труба гофр")
        add("electrical_wiring", "electro_box", sockets + 1, "room", "Подрозетники", ["подрозетник", "установочн"],
            must=r"^(подрозетник|коробка установочн)")
    add("electrical_fittings", "socket", sockets, "room", "Розетки",
        ["ip44", "влагозащ"] if wet else ["заземлен"])
    add("electrical_fittings", "switch", 1, "room", "Выключатель", ["1-клавиш", "одноклавиш"], must=r"^выключатель (1|одно)-?клавиш(?!.*(бра|светильн))")
    if wet:
        add("electrical_fittings", "light", lights, "ceiling", "Светильники влагозащищённые", ["ip44", "ванн"],
            must=r"ip ?(4[4-9]|6\d)|влагозащ|для ванн")
    elif prof.get("cold"):
        add("electrical_fittings", "light", 1, "ceiling", "Светильник", ["настенно-потолочн"], must=r"^светильник")
    else:
        add("electrical_fittings", "light", 1 if room.area < 16 else 2, "ceiling", "Люстра", ["потолочн"], must=r"^люстр")
        if repair == "designer":
            add("electrical_fittings", "light", math.ceil(room.area / 3), "ceiling", "Точечные светильники",
                ["точечн", "встраив"], must=r"точечн|встраив")
    if capital and room.type in ("bathroom", "toilet", "kitchen"):
        add("ventilation", "fan", 1, "room", "Вытяжной вентилятор", ["обратн"], must=r"^вентилятор")
    if capital and room.type == "bathroom":
        add("heating", "heating_mat", floor, "floor", "Тёплый пол", ["плитк", "мат"], must=r"тепл\w* пол|мат")
        add("heating", "thermostat", 1, "room", "Терморегулятор тёплого пола", must=r"^терморегулятор")
    if capital and room.type in WET:
        if room.type == "bathroom":
            add("plumbing", "plumbing_fixture", 1, "room", "Смеситель для ванны / душа", ["для ванн", "душ"],
                must=r"смеситель для (ванн|душ)")
            add("plumbing", "plumbing_fixture", 1, "room", "Смеситель для раковины", ["для раковин"],
                must=r"смеситель для раковин")
        add("plumbing", "plumbing_fixture", 1, "room", "Унитаз", ["компакт"], must=r"^унитаз(?!.*(без бачка|дачн))")
        add("plumbing", "pipe", 6, "room", "Фитинги для разводки воды", ["ppr", "полипропилен"], must=r"^(муфта|угольник|тройник|уголок|отвод).*(ppr|pp-r|полипроп)")
    if wet:
        add("sealing", "sealant", 2, "room", "Санитарный герметик", ["санитар"], must=r"санитар")

    # --- стены ---
    if wall_fin == "tile":
        add("tiling", "tile", walls, "walls", "Плитка настенная", ["стен", "настен"], require={"moisture_resistant": True} if wet else {})
        add("tiling", "tile_adhesive", walls, "walls", "Плиточный клей (стены)")
        add("tiling", "grout", walls, "walls", "Затирка (стены)", ["водоотталк"] if wet else [])
    elif wall_fin == "panels":
        add("wall_panels", "wall_panel", walls, "walls", "Стеновые панели", ["пвх"] if wet or prof.get("cold") else [])
        add("wall_panels", "fastener", 1, "walls", "Кляймеры / стартовый профиль", ["кляймер", "стартов"], optional=True,
            must=r"кляймер|стартов")
    else:
        if capital:
            add("puttying", "putty", walls, "walls", "Шпаклёвка стартовая", ["старт", "базов"], ctx={"putty_layer": "start"},
                must=r"^(?!.*(финиш|фасад))шпатл")
            add("puttying", "putty", walls, "walls", "Шпаклёвка финишная", ["финиш"], ctx={"putty_layer": "finish"},
                must=r"финиш")
        else:
            add("priming", "primer", walls, "walls", "Грунтовка стен", ["глубок"], must=r"глубок")
        if wall_fin == "wallpaper":
            pref = ["бумажн", "e1"] if prof.get("eco") else (["моющ"] if prof.get("grease") else ["флизелин"])
            add("wallpapering", "wallpaper", walls, "walls", "Обои", pref)
            add("wallpapering", "wallpaper_glue", walls, "walls", "Клей для обоев", ["флизелин"])
        else:
            pref = ["моющ", "влагост"] if (wet or room.type in ("kitchen", "hallway", "kids")) else ["интерьер", "стен"]
            add("painting", "paint", walls, "walls", "Краска для стен", pref, ctx={"layers": 2})
            add("painting", "tool", 1, "walls", "Валик малярный", ["валик"], optional=True, must=r"^валик")
        if repair == "designer" and room.type in ("living", "bedroom", "hallway"):
            add("decorative_finish", "decor_plaster", walls * 0.25, "walls", "Декоративная штукатурка (акцентная стена)",
                must=r"^(покрытие декоратив|штукатурка декоратив|микроцемент|декоративн)")

    # --- потолок ---
    if repair == "designer" and wet:
        add("ceiling", "ceiling_panel", ceil, "ceiling", "Реечный / кассетный потолок", ["реечн"],
            must=r"реечн|кассетн|рейк")
    else:
        add("painting", "paint", ceil, "ceiling", "Краска для потолка", ["потол"], ctx={"layers": 2})
        if repair == "designer":
            add("ceiling", "molding", room.perimeter, "ceiling", "Потолочный плинтус", ["потолоч", "галтель"])

    # --- пол ---
    if floor_fin == "tile":
        add("tiling", "tile", floor, "floor", "Плитка / керамогранит для пола",
            ["пол", "керамогранит", "противоскольз"] + (["морозост"] if prof.get("cold") else []),
            require={"frost_resistant": True} if prof.get("cold") else {})
        add("tiling", "tile_adhesive", floor, "floor", "Плиточный клей (пол)", ["керамогранит"])
        add("tiling", "grout", floor, "floor", "Затирка (пол)")
    elif floor_fin in ("laminate", "spc"):
        wear = 33 if room.type in ("hallway", "kitchen", "kids") else 32
        add("laminate", "laminate", floor, "floor", "Кварцвинил SPC" if floor_fin == "spc" else "Ламинат",
            ["spc", "кварцвинил"] if floor_fin == "spc" else ["ламинат"], require={"wear_class_min": wear})
        add("laminate", "underlay", floor, "floor", "Подложка", ["spc"] if floor_fin == "spc" else ["ламинат"])
    elif floor_fin == "linoleum":
        add("soft_flooring", "linoleum", floor, "floor", "Линолеум", ["линолеум"])
    if floor_fin != "tile":
        add("skirting", "skirting", room.skirting_length, "floor", "Плинтус напольный", ["кабель-канал"], must=r"^плинтус")
        add("skirting", "skirting_accessory", 4 + 2 * room.doors, "floor", "Углы и заглушки для плинтуса", ["угол", "заглушк"],
            optional=True, must=r"угол|заглушк")

    # --- завершающие ---
    if capital and room.doors and room.type not in ("balcony",):
        add("doors", "door", room.doors, "room", "Межкомнатная дверь", ["межкомнат", "полотно"], must=r"полотно|двер")
        add("doors", "door_part", room.doors, "room", "Дверная коробка", ["коробк"], must=r"короб")
        add("doors", "foam", room.doors, "room", "Монтажная пена", ["монтажн"], must=r"пена")
    if capital and room.windows:
        add("windows_slopes", "window_sill", room.windows, "room", "Подоконник", ["подоконник"], must=r"^подоконник")
    return S
