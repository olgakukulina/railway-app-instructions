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


def _clean_ai_text(text: str) -> str:
    """Убираем отсылки к таблицам и оборванные хвосты вроде «Согласно ведомости (»."""
    lines = []
    for line in str(text or "").splitlines():
        if _TABLE_REF_RE.match(line.strip()):
            continue
        line = re.sub(
            r"\s*(?:см\.?\s*)?таблиц\w*\s+\d+(?:\.\d+)*(?:[^.]*\.)?",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        line = re.sub(r"[\s:(,\-–—]*$", "", line).strip()
        if line:
            lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\(\s*$", "", cleaned).strip()
    return cleaned


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

    appendices = ai_result.get("appendices") or []

    return {
        "document_id": task_id,
        "station_name": station_name,
        "region": region,
        "organization": organization,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
        "appendices": appendices,
    }