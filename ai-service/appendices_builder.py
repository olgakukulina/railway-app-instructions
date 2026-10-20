from __future__ import annotations
import logging
import math
import re
from typing import Any

log = logging.getLogger(__name__)


def build_appendices(passport_data: dict[str, Any]) -> list[dict[str, Any]]:
    appendices: list[dict[str, Any]] = []
    meta = passport_data.get("meta") or {}
    company = meta.get("company_name") or "Предприятие"
    station = meta.get("station_name") or "Станция"

    # Приложение 1 - Схема
    appendices.append({
        "title": f"Схема железнодорожного пути необщего пользования {company}",
        "type": "image",
        "source_url": "images/appendix1_scheme.png",
    })

    # Приложение 2 - Ведомость путей (с объединёнными заголовками)
    track_table = _build_track_registry(passport_data)
    if track_table:
        appendices.append({
            "title": "Ведомость железнодорожного пути необщего пользования",
            "type": "table",
            "table": track_table,
        })

    # Приложение 3 - Ведомость стрелочных переводов
    switch_table = _build_switch_registry(passport_data)
    if switch_table:
        appendices.append({
            "title": "Ведомость стрелочных переводов железнодорожного пути необщего пользования",
            "type": "table",
            "table": switch_table,
        })

    # Приложение 4 - Нормы закрепления (complex-таблица)
    brake_table = _build_brake_norms(passport_data)
    if brake_table:
        appendices.append({
            "title": "Порядок и нормы закрепления вагонов на железнодорожном пути необщего пользования",
            "type": "table",
            "table": brake_table,
        })

    # Приложение 5 - Продольный профиль
    appendices.append({
        "title": f"Продольный профиль железнодорожного пути необщего пользования {company}",
        "type": "image",
        "source_url": "images/appendix5_profile.png",
    })

    # Приложение 6 - Расчёт норм (complex-приложение: текст → таблица → формулы → текст)
    calc_data = _build_brake_calculation(passport_data)
    appendices.append({
        "title": "Расчёт норм закрепления вагонов",
        "type": "complex",
        "blocks": calc_data["blocks"] if calc_data else [],
    })

    # Приложение 7 - Схема маршрута
    appendices.append({
        "title": "Схема маршрута технологического прохода по железнодорожному пути необщего пользования",
        "type": "image",
        "source_url": "images/appendix7_techpass.png",
    })

    log.info("Собрано приложений: %s", len(appendices))
    return appendices


def _build_track_registry(passport_data: dict) -> dict | None:
    tracks: dict[str, dict] = {}

    for table in passport_data.get("source_tables", []):
        title = str(table.get("title", "")).lower()
        headers = table.get("headers") or []
        rows = table.get("rows") or []
        headers_str = " ".join(str(h).lower() for h in headers)

        is_registry = ("ведомость путей" in title or ("границ" in headers_str and "специализац" in headers_str))
        is_lengths = ("длине путей" in title or ("полная" in headers_str and "полезная" in headers_str))

        if is_registry:
            for row in rows:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                path_num = str(row[0]).strip()
                # ДОБАВЛЕНА ПРОВЕРКА НА "ИТОГО" (регистронезависимая)
                if not path_num or path_num.lower() in ("№ пут", "№ пути", "итого", "----", "-"):
                    continue
                tracks.setdefault(path_num, {})
                tracks[path_num]["path_number"] = path_num
                tracks[path_num]["specialization"] = str(row[1]).strip() if len(row) > 1 else "-"
                tracks[path_num]["from_label"] = str(row[2]).strip() if len(row) > 2 else "-"
                tracks[path_num]["to_label"] = str(row[3]).strip() if len(row) > 3 else "-"

        elif is_lengths:
            for row in rows:
                if not isinstance(row, list) or len(row) < 4:
                    continue
                path_num = str(row[0]).strip()
                # ДОБАВЛЕНА ПРОВЕРКА НА "ИТОГО"
                if not path_num or path_num.lower() in ("№ пут", "№ пути", "итого", "-"):
                    continue
                tracks.setdefault(path_num, {})
                tracks[path_num]["path_number"] = path_num
                if len(row) > 3:
                    tracks[path_num]["length_full_m"] = str(row[3]).strip()
                if len(row) > 4:
                    tracks[path_num]["length_useful_m"] = str(row[4]).strip()

    if not tracks:
        section_1 = passport_data.get("section_1_general_characteristics", {})
        path_lengths = section_1.get("1.6", {}).get("path_lengths", {})
        if path_lengths.get("available"):
            paths = path_lengths.get("data", {}).get("paths", [])
            for p in paths:
                path_num = str(p.get("path_number", "")).strip()
                if not path_num or path_num.lower() == "итого":
                    continue
                tracks[path_num] = {
                    "path_number": path_num,
                    "specialization": p.get("specialization", "-"),
                    "from_label": p.get("from_label", "-"),
                    "to_label": p.get("to_label", "-"),
                    "length_full_m": str(p.get("length_full_m", "-")),
                    "length_useful_m": str(p.get("length_useful_m", "-")),
                }

    if not tracks:
        return None

    flat_headers = [
        "№ Пути", "Назначение пути", "Границы пути (От)", "Границы пути (До)",
        "Полная длина, м", "Полезная длина, м", "Вместимость, усл. ваг.",
        "Вместимость мест погрузки и выгрузки, физ.ваг.", "Мин. радиус кривых, м",
        "Максимальный уклон (В какую сторону)", "Максимальный уклон (Величина, тыс.)",
        "Тип рельсов", "Макс. допус. скор. движ., км/ч", "Наличие электрич. изоляции пути",
    ]

    header_structure = [
        (2, 1, "№ Пути"), (2, 1, "Назначение пути"),
        (1, 2, "Границы пути"),
        (2, 1, "Полная длина, м"), (2, 1, "Полезная длина, м"),
        (2, 1, "Вместимость, усл. ваг."), (2, 1, "Вместимость мест погрузки и выгрузки, физ.ваг."),
        (2, 1, "Мин. радиус кривых, м"),
        (1, 2, "Максимальный уклон"),
        (2, 1, "Тип рельсов"), (2, 1, "Макс. допус. скор. движ., км/ч"),
        (2, 1, "Наличие электрич. изоляции пути"),
        (1, 1, "От"), (1, 1, "До"),
        (1, 1, "В какую сторону"), (1, 1, "Величина, тыс."),
    ]

    rows_out = []
    for path_num, data in sorted(tracks.items()):
        rows_out.append([
            data.get("path_number", "-"), data.get("specialization", "-"),
            data.get("from_label", "-"), data.get("to_label", "-"),
            data.get("length_full_m", "-"), data.get("length_useful_m", "-"),
            "-", "-", "-", "Упор",
            str(data.get("slope", "-")), "-", "15", "нет",
        ])

    return {
        "headers": flat_headers,
        "header_structure": header_structure,
        "rows": rows_out,
    }


def _build_switch_registry(passport_data: dict) -> dict | None:
    for table in passport_data.get("source_tables", []):
        title = str(table.get("title", "")).lower()
        headers = table.get("headers") or []
        headers_str = " ".join(str(h).lower() for h in headers)

        is_switch = ("стрелочн" in title or "крестовин" in headers_str or "марка" in headers_str)
        if is_switch:
            rows = table.get("rows") or []
            if rows and headers:
                target_headers = [
                    "Номер стрелочного перевода", "Способ управления стрелкой",
                    "Кто переводит стрелку", "Тип рельсов", "Марка крестовины",
                    "Допускаемая скорость движения (км/час) по прямому пути",
                    "Допускаемая скорость движения (км/час) на боковой путь", "Вид перевода",
                ]
                mapped_rows = []
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    padded_row = row + ["-"] * (len(target_headers) - len(row))
                    mapped_rows.append(padded_row[:len(target_headers)])
                return {"headers": target_headers, "rows": mapped_rows}

    return None


def calculate_brake_shoes(axes: int, slope: float, storm_wind: bool = True) -> int:
    K = (axes * (4 * slope + 1)) / 200
    if storm_wind:
        K += (7 * axes) / 200
    return math.ceil(K)


def _extract_slope_for_path(passport_data: dict, path_num: str) -> float | None:
    for item in passport_data.get("source_narrative", []):
        text = str(item.get("text", " "))
        patterns = [
            rf"[Пп]уть\s+№?\s*{re.escape(path_num)}\b[^.]{{0,200}}?уклон[^.]{{0,50}}?(\d+[.,]\d+)",
            rf"уклон[^.]{{0,100}}?[Пп]уть\s+№?\s*{re.escape(path_num)}\b[^.]{{0,100}}?(\d+[.,]\d+)",
            rf"уклон[^.]{{0,50}}?(\d+[.,]\d+)\s*тыс",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", "."))
                except (ValueError, IndexError):
                    continue
    return None


def _build_brake_norms(passport_data: dict) -> dict | None:
    """Приложение 4: complex-таблица с текстовыми блоками и rowspan."""
    tracks = _build_track_registry(passport_data)
    if not tracks:
        return None

    flat_headers = [
        "№ пути", "Максимальный уклон", "С какой стороны производится закрепление",
        "Нормы закрепления (Количество тормозных башмаков)",
        "Нормы закрепления (Количество осей)",
        "Кто и когда производит закрепление", "Кто и когда снимает закрепление",
    ]

    header_structure = [
        (2, 1, "№ пути"), (2, 1, "Максимальный уклон"),
        (2, 1, "С какой стороны производится закрепление"),
        (1, 2, "Нормы закрепления"),
        (2, 1, "Кто и когда производит закрепление"), (2, 1, "Кто и когда снимает закрепление"),
        (1, 1, "Количество тормозных башмаков"), (1, 1, "Количество осей"),
    ]

    DEFAULT_SLOPE = 1.0
    rows = []
    who_fixes = "Составитель поездов станции до отцепки локомотива в присутствии ответственного работника предприятия с докладом машинисту, ДСЦ"
    who_removes = "Составитель поездов станции после прицепки локомотива в присутствии ответственного работника предприятия с докладом машинисту, ДСЦ"

    for track_row in tracks["rows"]:
        path_num = track_row[0]
        from_label = track_row[2]
        to_label = track_row[3]
        length = track_row[4]
        slope = _extract_slope_for_path(passport_data, path_num) or DEFAULT_SLOPE

        track_desc = (
            f"Путь № {path_num}\n"
            f"Запрещается оставлять вагоны без локомотива на участках пути № {path_num}:\n"
            f"- от {from_label} до {to_label}, протяжённостью {length} м."
        )
        rows.append({"type": "text_block", "text": track_desc, "colspan": 7})

        norms = []
        for axes in (4, 8, 12, 20, 24, 28):
            shoes = calculate_brake_shoes(axes, slope)
            norms.append({"slope": str(slope), "shoes": str(shoes), "axes": str(axes)})

        rows.append({
            "type": "norm_block",
            "path_cell": {"text": f"Путь № {path_num}\n{from_label} – {to_label}", "rowspan": 6},
            "side_cell": {"text": "Стр.132", "rowspan": 6},
            "who_fixes_cell": {"text": who_fixes, "rowspan": 6},
            "who_removes_cell": {"text": who_removes, "rowspan": 6},
            "norms": norms,
        })

    if not rows:
        return None

    return {
        "headers": flat_headers,
        "header_structure": header_structure,
        "rows": rows,
        "complex": True,
    }


def _build_brake_calculation(passport_data: dict) -> dict | None:
    tracks = _build_track_registry(passport_data)
    DEFAULT_SLOPE = 1.0
    blocks = []

    if not tracks:
        blocks.append({"type": "heading", "text": "РАСЧЁТ норм закрепления вагонов", "level": 1})
        blocks.append({"type": "text",
                       "text": "Данные для расчёта отсутствуют. Требуется ручное заполнение."})
        return {"blocks": blocks}

    blocks.append({"type": "heading",
                   "text": "РАСЧЁТ норм закрепления вагонов на железнодорожном пути необщего пользования",
                   "level": 1})

    for track_row in tracks["rows"]:
        path_num = track_row[0]
        from_label = track_row[2]
        to_label = track_row[3]
        length = track_row[4]
        slope = _extract_slope_for_path(passport_data, path_num) or DEFAULT_SLOPE

        blocks.append({"type": "heading", "text": f"Путь № {path_num}", "level": 2})
        blocks.append({"type": "text",
                       "text": f"От знака {from_label} до знака {to_label}\n({from_label} – {to_label})"})
        blocks.append({"type": "text",
                       "text": f"Участок пути № {path_num} от знака {from_label} до знака {to_label}, "
                               f"протяжённостью {length} м. Установка вагонов в пределах границ участка "
                               f"производится в произвольном месте."})
        blocks.append({"type": "text",
                       "text": "Результаты расчёта норм закрепления со стороны стрелочного перевода сведены в таблицу:"})

        # Таблица расчёта
        table_headers = ["Уклоны, тыс.", "Расстояние, м", "Оси", "∑ осей", "т/башмаки", "∑ т/б"]
        table_rows = []
        cumulative_axes = 0
        cumulative_shoes = 0.0
        for axes in (4, 8, 12, 20, 24, 28):
            shoes = calculate_brake_shoes(axes, slope)
            cumulative_axes += axes
            cumulative_shoes += shoes
            table_rows.append([str(slope), "-", str(axes), str(cumulative_axes), str(shoes), f"{cumulative_shoes:.2f}"])

        blocks.append({"type": "table", "table": {"headers": table_headers, "rows": table_rows}})

        # Формулы расчёта (Обычный текст)
        blocks.append({"type": "text", "text": "Расчёт норм закрепления со стороны стрелочного перевода:"})
        if table_rows:
            for row in table_rows:
                slope_v, axes_v, shoes_v = row[0], row[2], row[4]
                # Текстовая формула без LaTeX
                formula = f"K = (N × (4i + 1)) / 200 + (7 × N) / 200 = ({axes_v} × (4 × {slope_v} + 1)) / 200 + (7 × {axes_v}) / 200 = {shoes_v} т/б;"
                blocks.append({"type": "formula", "text": formula})

        # Пропорции и расчёты (Обычный текст)
        last_row = table_rows[-1]
        last_axes = float(last_row[2])
        last_shoes = float(last_row[4])

        blocks.append({"type": "text",
                       "text": f"На уклоне {slope} тыс. в сторону стрелочного перевода могут располагаться "
                               f"{last_axes:.2f} оси, для которых требуется {last_shoes:.2f} тормозных башмака."})

        blocks.append({"type": "text",
                       "text": "Определим количество осей, удерживаемых одним тормозным башмаком, из следующей пропорции:"})
        blocks.append({"type": "formula", "text": f"{last_axes:.2f} оси – {last_shoes:.2f} т/б"})
        blocks.append({"type": "formula", "text": "X – 1 т/б"})
        blocks.append({"type": "formula",
                       "text": f"X = {last_axes:.2f} / {last_shoes:.2f} = {last_axes/last_shoes:.2f} оси."})

        blocks.append({"type": "text",
                       "text": "Определим количество осей, удерживаемых двумя тормозными башмаками, из следующей пропорции:"})
        blocks.append({"type": "formula", "text": f"{last_axes:.2f} оси – {last_shoes:.2f} т/б"})
        blocks.append({"type": "formula", "text": "X – 2 т/б"})
        blocks.append({"type": "formula",
                       "text": f"X = ({last_axes:.2f} × 2) / {last_shoes:.2f} = {last_axes*2/last_shoes:.2f} = "
                               f"{round(last_axes*2/last_shoes)} оси."})

    return {"blocks": blocks}