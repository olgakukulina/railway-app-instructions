

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
    appendices.append({
        "title": f"Схема железнодорожного пути необщего пользования {company}",
        "type": "image",
        "source_url": "images/appendix1_scheme.png",
    })
    track_table = _build_track_registry(passport_data)
    if track_table:
        appendices.append({
            "title": "Ведомость железнодорожного пути необщего пользования",
            "type": "table",
            "table": track_table,
        })
    switch_table = _build_switch_registry(passport_data)
    if switch_table:
        appendices.append({
            "title": "Ведомость стрелочных переводов железнодорожного пути необщего пользования",
            "type": "table",
            "table": switch_table,
        })

    brake_table = _build_brake_norms(passport_data)
    if brake_table:
        appendices.append({
            "title": "Порядок и нормы закрепления вагонов на железнодорожном пути необщего пользования",
            "type": "table",
            "table": brake_table,
        })
    appendices.append({
        "title": f"Продольный профиль железнодорожного пути необщего пользования {company}",
        "type": "image",
        "source_url": "images/appendix5_profile.png",
    })
    calc_table = _build_brake_calculation(passport_data)
    if calc_table:
        appendices.append({
            "title": "Расчёт норм закрепления вагонов",
            "type": "table",
            "table": calc_table,
        })
    appendices.append({
        "title": "Схема маршрута технологического прохода по железнодорожному пути необщего пользования",
        "type": "image",
        "source_url": "images/appendix7_techpass.png",
    })

    log.info("Собрано приложений: %s", len(appendices))
    return appendices


def _build_track_registry(passport_data: dict) -> dict | None:
    tracks: dict[str, dict] = {}

    # 1. Из source_tables
    for table in passport_data.get("source_tables", []):
        title = str(table.get("title", "")).lower()
        headers = table.get("headers") or []
        rows = table.get("rows") or []
        headers_str = " ".join(str(h).lower() for h in headers)

        is_registry = (
            "ведомость путей" in title
            or ("границ" in headers_str and "специализац" in headers_str)
        )
        is_lengths = (
            "длине путей" in title
            or ("полная" in headers_str and "полезная" in headers_str)
        )

        if is_registry:
            for row in rows:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                path_num = str(row[0]).strip()
                if not path_num or path_num in ("№ пут", "№ пути", "Итого", "----"):
                    continue
                tracks.setdefault(path_num, {})
                tracks[path_num]["path_number"] = path_num
                tracks[path_num]["from_label"] = str(row[1]).strip() if len(row) > 1 else "-"
                tracks[path_num]["to_label"] = str(row[2]).strip() if len(row) > 2 else "-"
                tracks[path_num]["specialization"] = str(row[3]).strip() if len(row) > 3 else "-"

        elif is_lengths:
            for row in rows:
                if not isinstance(row, list) or len(row) < 4:
                    continue
                path_num = str(row[0]).strip()
                if not path_num or path_num in ("№ пут", "№ пути", "Итого"):
                    continue
                tracks.setdefault(path_num, {})
                tracks[path_num]["path_number"] = path_num
                if len(row) > 3:
                    tracks[path_num]["length_full_m"] = str(row[3]).strip()
                if len(row) > 4:
                    tracks[path_num]["length_useful_m"] = str(row[4]).strip()

    # 2. Fallback: из section_1.path_lengths
    if not tracks:
        section_1 = passport_data.get("section_1_general_characteristics", {})
        path_lengths = section_1.get("1.6", {}).get("path_lengths", {})
        if path_lengths.get("available"):
            paths = path_lengths.get("data", {}).get("paths", [])
            for p in paths:
                path_num = str(p.get("path_number", "")).strip()
                if not path_num:
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

    headers = [
        "№ пути",
        "Специализация",
        "Границы (от)",
        "Границы (до)",
        "Полная длина, м",
        "Полезная длина, м",
    ]
    rows_out = []
    for path_num, data in sorted(tracks.items()):
        rows_out.append([
            data.get("path_number", "-"),
            data.get("specialization", "-"),
            data.get("from_label", "-"),
            data.get("to_label", "-"),
            data.get("length_full_m", "-"),
            data.get("length_useful_m", "-"),
        ])

    return {"headers": headers, "rows": rows_out}

def _build_switch_registry(passport_data: dict) -> dict | None:
    for table in passport_data.get("source_tables", []):
        title = str(table.get("title", "")).lower()
        headers = table.get("headers") or []
        headers_str = " ".join(str(h).lower() for h in headers)

        is_switch = (
            "стрелочн" in title
            or "крестовин" in headers_str
            or "марка" in headers_str
        )
        if is_switch:
            rows = table.get("rows") or []
            if rows and headers:
                return {"headers": headers, "rows": rows}
    return None

def calculate_brake_shoes(axes: int, slope: float, storm_wind: bool = True) -> int:

    K = (axes * (4 * slope + 1)) / 200
    if storm_wind:
        K += (7 * axes) / 200
    return math.ceil(K)


def _extract_slope_for_path(passport_data: dict, path_num: str) -> float | None:
    for item in passport_data.get("source_narrative", []):
        text = str(item.get("text", ""))
        patterns = [
            rf"[Пп]уть\s*№?\s*{re.escape(path_num)}\b[^.]{{0,200}}?уклон[^.]{{0,50}}?(\d+[.,]\d+)",
            rf"уклон[^.]{{0,100}}?[Пп]уть\s*№?\s*{re.escape(path_num)}\b[^.]{{0,100}}?(\d+[.,]\d+)",
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

    for table in passport_data.get("source_tables", []):
        title = str(table.get("title", "")).lower()
        if "закрепл" in title and ("норм" in title or "порядок" in title):
            headers = table.get("headers") or []
            rows = table.get("rows") or []
            if headers and rows:
                return {"headers": headers, "rows": rows}
    tracks = _build_track_registry(passport_data)
    if not tracks:
        return None

    headers = [
        "№ пути",
        "Максимальный уклон, тыс.",
        "Сторона закрепления",
        "Кол-во тормозных башмаков",
        "Кол-во осей",
        "Кто производит закрепление",
        "Кто снимает закрепление",
    ]

    DEFAULT_SLOPE = 1.0  # типовой уклон, если не нашли в техпаспорте

    rows = []
    for track_row in tracks["rows"]:
        path_num = track_row[0]
        slope = _extract_slope_for_path(passport_data, path_num) or DEFAULT_SLOPE
        for axes in (4, 8, 12, 20, 24, 28):
            shoes = calculate_brake_shoes(axes, slope)
            rows.append([
                f"Путь №{path_num}",
                str(slope),
                "СП",
                str(shoes),
                str(axes),
                "Составитель поездов станции до отцепки локомотива в присутствии ответственного работника предприятия с докладом машинисту, ДСЦ",
                "Составитель поездов станции после прицепки локомотива в присутствии ответственного работника предприятия с докладом машинисту, ДСЦ",
            ])

    if not rows:
        return None
    return {"headers": headers, "rows": rows}


def _build_brake_calculation(passport_data: dict) -> dict | None:
    tracks = _build_track_registry(passport_data)
    if not tracks:
        return None

    headers = ["Параметр", "Значение"]
    rows = []
    DEFAULT_SLOPE = 1.0

    for track_row in tracks["rows"]:
        path_num = track_row[0]
        slope = _extract_slope_for_path(passport_data, path_num) or DEFAULT_SLOPE
        rows.append([f"Путь №{path_num}: максимальный уклон, тыс.", str(slope)])
        rows.append([
            f"Путь №{path_num}: формула расчёта",
            "K = N·(4i + 1)/200 + 7N/200",
        ])
        for axes in (4, 8, 12, 20, 24, 28):
            shoes = calculate_brake_shoes(axes, slope)
            rows.append([
                f"Путь №{path_num}: {axes} осей - башмаков",
                str(shoes),
            ])

    if not rows:
        return None
    return {"headers": headers, "rows": rows}