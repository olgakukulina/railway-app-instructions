"""Convert AI document_sections → assembler InstructionDocument JSON."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


SECTION_ORDER = [
    "ОБЩАЯ ХАРАКТЕРИСТИКА ПУТИ НЕОБЩЕГО ПОЛЬЗОВАНИЯ",
    "ПОРЯДОК ПОДАЧИ И УБОРКИ ВАГОНОВ",
    "МАНЕВРОВАЯ РАБОТА",
    "ЗАКРЕПЛЕНИЕ ВАГОНОВ",
    "ТЕХНИКА БЕЗОПАСНОСТИ",
]

_TABLE_REF_RE = re.compile(
    r"(?im)^\s*(см\.?\s*)?таблиц\w*\s+\d+(?:\.\d+)?.*$"
)

# Иногда локальная модель, вместо связного текста раздела, вставляет свой
# собственный заголовок документа/раздела или дословно пересказывает сырые
# табличные данные из техпаспорта (пикеты, номера путей). Это ломает вёрстку
# итогового документа — такие строки нужно вычищать до сборки.
_PREAMBLE_LINE_RE = re.compile(
    r"(?im)^\s*(ИНСТРУКЦИЯ\b|"
    r"о порядке обслуживания и организации движения|"
    r"на железнодорожном пути необщего пользования)"
)
_SECTION_HEADER_LINE_RE = re.compile(r"(?im)^\s*РАЗДЕЛ\s+\d+[.\s].*$")
_CANONICAL_TITLE_LINE_RE = re.compile(
    "(?im)^\\s*(?:" + "|".join(re.escape(t) for t in SECTION_ORDER) + ")\\s*$"
)
_PIKET_RE = re.compile(r"пк\s*\d+\+\d+", re.IGNORECASE)


def _looks_like_table_dump(line: str) -> bool:
    if len(_PIKET_RE.findall(line)) >= 2:
        return True
    digits = sum(ch.isdigit() for ch in line)
    return len(line) > 30 and digits / len(line) > 0.3


def _strip_generated_artifacts(text: str) -> str:
    """Убирает заголовки документа/раздела и сырые табличные дампы, которые
    иногда просачиваются в текст раздела из ответа модели."""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if _PREAMBLE_LINE_RE.match(stripped):
            continue
        if _SECTION_HEADER_LINE_RE.match(stripped):
            continue
        if _CANONICAL_TITLE_LINE_RE.match(stripped):
            continue
        if _looks_like_table_dump(stripped):
            continue
        kept.append(line)
    return "\n".join(kept)


def _map_table_to_section(number: str, title: str) -> str:
    """Куда положить таблицу техпаспорта в структуре инструкции."""
    low = f"{number} {title}".lower()
    if any(k in low for k in ("закреп", "противоугон", "башмак", "тормозн")):
        return SECTION_ORDER[3]
    if any(k in low for k in ("маневро", "радиосвяз", "локомотив")):
        return SECTION_ORDER[2]
    if any(k in low for k in ("подач", "уборк", "грузов", "вместим", "фронт")):
        return SECTION_ORDER[1]
    if any(k in low for k in ("охран", "негабарит", "безопасн", "опасн")):
        return SECTION_ORDER[4]
    return SECTION_ORDER[0]


def _clean_ai_text(text: str) -> str:
    """Убираем отсылки к таблицам и оборванные хвосты вроде «Согласно ведомости (»."""
    lines = []
    for line in _strip_generated_artifacts(str(text or "")).splitlines():
        if _TABLE_REF_RE.match(line.strip()):
            continue
        line = re.sub(
            r"\s*(?:см\.?\s*)?таблиц\w*\s+\d+(?:\.\d+)*(?:[^.]*\.)?",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        # «Согласно ведомости путей (» / «приведено в (»
        line = re.sub(
            r"[\s:(,\-–—]*$",
            "",
            line,
        ).strip()
        if line and not line.endswith((".", ";", ":")):
            # не трогаем нормальные заголовки вида «1.1. Местоположение»
            if not re.match(r"^\d+(\.\d+)*\.?\s+\S+", line):
                pass
        if line:
            lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\(\s*$", "", cleaned).strip()
    return cleaned


def _assembler_table(raw: dict[str, Any]) -> dict[str, Any] | None:
    rows = raw.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    headers = raw.get("headers") or []
    if headers and not isinstance(headers, list):
        headers = []
    title = str(raw.get("title") or "Таблица").strip()
    return {
        "title": title,
        "headers": [str(h) for h in headers],
        "rows": [[str(c) for c in row] for row in rows if isinstance(row, list)],
    }


def _attach_tables(
    sections: list[dict[str, Any]],
    passport_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Вставляет таблицы техпаспорта в секции; невошедшие — в приложения."""
    source_tables = passport_data.get("source_tables") or []
    if not isinstance(source_tables, list) or not source_tables:
        return []

    title_to_canonical = {
        (name.title() if name.isupper() else name): name for name in SECTION_ORDER
    }
    by_canonical: dict[str, dict[str, Any]] = {}
    for section in sections:
        canonical = title_to_canonical.get(section["title"], section["title"])
        by_canonical[canonical] = section
        section.setdefault("tables", [])

    appendices: list[dict[str, Any]] = []
    for raw in source_tables:
        if not isinstance(raw, dict):
            continue
        table = _assembler_table(raw)
        if not table:
            continue
        number = str(raw.get("number") or "")
        title = str(raw.get("title") or table["title"])
        target = _map_table_to_section(number, title)
        section = by_canonical.get(target)
        if section is not None:
            section["tables"].append(table)
        else:
            appendices.append({"title": title, "type": "table", "table": table})

    return appendices


def to_assembler_document(
    task_id: str,
    passport_data: dict[str, Any],
    ai_result: dict[str, Any],
    region: str = "chita",
) -> dict[str, Any]:
    meta = passport_data.get("meta") or {}
    station_name = (
        ai_result.get("station")
        or meta.get("station_name")
        or "Неизвестная станция"
    )
    organization = meta.get("company_name") or ""

    document_sections = ai_result.get("document_sections") or {}
    sections: list[dict[str, Any]] = []
    order = 1

    for title in SECTION_ORDER:
        text = document_sections.get(title)
        if text is None:
            continue
        sections.append(
            {
                "id": f"{order:04d}",
                "order": order,
                "title": title.title() if title.isupper() else title,
                "text": _clean_ai_text(str(text)),
                "tables": [],
            }
        )
        order += 1

    for title, text in document_sections.items():
        if title in SECTION_ORDER:
            continue
        sections.append(
            {
                "id": f"{order:04d}",
                "order": order,
                "title": str(title),
                "text": _clean_ai_text(str(text)),
                "tables": [],
            }
        )
        order += 1

    if not sections:
        sections.append(
            {
                "id": "0001",
                "order": 1,
                "title": "Общие сведения",
                "text": "Текст инструкции не был сгенерирован.",
                "tables": [],
            }
        )

    appendices = _attach_tables(sections, passport_data)

    return {
        "document_id": task_id,
        "station_name": station_name,
        "region": region,
        "organization": organization,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
        "appendices": appendices,
    }
