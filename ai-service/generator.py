"""Instruction generation: local Qwen, document narrative, or facts fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from ai_engine import StationInstructionAI

log = logging.getLogger(__name__)

SECTIONS = [
    "ОБЩАЯ ХАРАКТЕРИСТИКА ПУТИ НЕОБЩЕГО ПОЛЬЗОВАНИЯ",
    "ПОРЯДОК ПОДАЧИ И УБОРКИ ВАГОНОВ",
    "МАНЕВРОВАЯ РАБОТА",
    "ЗАКРЕПЛЕНИЕ ВАГОНОВ",
    "ТЕХНИКА БЕЗОПАСНОСТИ",
]

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "ОБЩАЯ ХАРАКТЕРИСТИКА ПУТИ НЕОБЩЕГО ПОЛЬЗОВАНИЯ": (
        "общая характеристика",
        "общие сведения",
        "характеристика пути",
    ),
    "ПОРЯДОК ПОДАЧИ И УБОРКИ ВАГОНОВ": (
        "подачи и уборки",
        "подача и уборка",
        "порядок подачи",
    ),
    "МАНЕВРОВАЯ РАБОТА": ("маневро",),
    "ЗАКРЕПЛЕНИЕ ВАГОНОВ": ("закреплени",),
    "ТЕХНИКА БЕЗОПАСНОСТИ": ("техника безопасности", "охрана труда", "требования безопасности"),
}


def _force_mock() -> bool:
    return os.getenv("AI_MOCK", "false").lower() in ("1", "true", "yes")


def _use_local_ai() -> bool:
    return os.getenv("USE_LOCAL_AI", "true").lower() in ("1", "true", "yes")


def _narrative(passport_data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = passport_data.get("source_narrative") or []
    return [x for x in raw if isinstance(x, dict) and str(x.get("text") or "").strip()]


def _narrative_substance(items: list[dict[str, Any]]) -> bool:
    total = sum(len(str(x.get("text") or "")) for x in items)
    return total >= 400 or len(items) >= 3


def _summarize_passport(passport_data: dict[str, Any]) -> str:
    meta = passport_data.get("meta") or {}
    bits = [
        f"станция: {meta.get('station_name') or 'н/д'}",
        f"организация: {meta.get('company_name') or 'н/д'}",
        f"пути: {meta.get('path_numbers') or 'н/д'}",
    ]
    return "; ".join(bits)


def _match_section_title(title: str) -> str | None:
    low = title.lower()
    for canonical, aliases in _SECTION_ALIASES.items():
        if any(a in low for a in aliases):
            return canonical

    # Numbered railway instruction outline
    if "раздел 1" in low or low.startswith("1."):
        return SECTIONS[0]
    if "раздел 2" in low or low.startswith("2."):
        return SECTIONS[1]
    if "раздел 3" in low or low.startswith("3."):
        return SECTIONS[2]
    if "раздел 4" in low or low.startswith("4."):
        return SECTIONS[3]
    if "раздел 5" in low or low.startswith("5.") or "охран" in low:
        return SECTIONS[4]
    return None


def from_narrative(passport_data: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build instruction sections from the uploaded document's own text."""
    meta = passport_data.get("meta") or {}
    station = meta.get("station_name") or "Неизвестная станция"

    buckets: dict[str, list[str]] = {name: [] for name in SECTIONS}
    extras: list[str] = []

    for item in items:
        title = str(item.get("title") or "Раздел").strip()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        body = f"{title}\n\n{text}" if title else text
        canonical = _match_section_title(title)
        if canonical:
            buckets[canonical].append(body)
        else:
            extras.append(body)

    document_sections: dict[str, str] = {}
    for name in SECTIONS:
        if buckets[name]:
            document_sections[name] = "\n\n".join(buckets[name])

    # Fallback: distribute whole narrative across canonical sections
    if len(document_sections) < 2:
        document_sections = {}
        chunks = [f"{t}\n\n{x}" for t, x in ((i.get("title"), i.get("text")) for i in items) if x]
        if not chunks:
            chunks = ["Текст исходного документа не извлечён."]
        per = max(1, (len(chunks) + len(SECTIONS) - 1) // len(SECTIONS))
        idx = 0
        for name in SECTIONS:
            part = chunks[idx: idx + per]
            idx += per
            if part:
                document_sections[name] = "\n\n---\n\n".join(part)
            if idx >= len(chunks):
                break
    elif extras:
        document_sections["ДОПОЛНИТЕЛЬНО / ПРИЛОЖЕНИЯ"] = "\n\n---\n\n".join(extras)

    return {
        "status": "success",
        "station": station,
        "document_sections": document_sections,
        "validation_errors": {},
        "mode": "document_narrative",
    }


def from_facts(passport_data: dict[str, Any]) -> dict[str, Any]:
    """Compose sections from structured available leaves (tech passport facts)."""
    meta = passport_data.get("meta") or {}
    station = meta.get("station_name") or "Неизвестная станция"
    company = meta.get("company_name") or ""

    facts: list[str] = []
    for key, value in passport_data.items():
        if not key.startswith("section_") or not isinstance(value, dict):
            continue
        for leaf_id, leaf in value.items():
            if not isinstance(leaf, dict) or not leaf.get("available"):
                continue
            data = leaf.get("data")
            source = leaf.get("source") or ""
            facts.append(f"[{leaf_id}] {json.dumps(data, ensure_ascii=False)} (источник: {source})")

    facts_block = "\n".join(facts) if facts else "Структурированные факты техпаспорта почти не извлечены."

    document_sections = {}
    for section in SECTIONS:
        document_sections[section] = (
            f"{section}\n\n"
            f"Организация: {company or 'н/д'}. Станция примыкания: {station}.\n\n"
            f"На основании извлечённых данных исходного документа:\n{facts_block}\n\n"
            f"Раздел подготовлен в режиме фактов (без LLM). "
            f"Для полноценной генерации используйте локальную модель Qwen (USE_LOCAL_AI=true)."
        )

    return {
        "status": "success",
        "station": station,
        "document_sections": document_sections,
        "validation_errors": {},
        "mode": "facts",
    }


def mock_generate(passport_data: dict[str, Any]) -> dict[str, Any]:
    meta = passport_data.get("meta") or {}
    station = meta.get("station_name") or "Неизвестная станция"
    summary = _summarize_passport(passport_data)

    document_sections = {}
    for section in SECTIONS:
        document_sections[section] = (
            f"{section}\n\n"
            f"Настоящий раздел инструкции подготовлен автоматически для станции «{station}».\n"
            f"Исходные данные техпаспорта: {summary}.\n\n"
            f"Это MOCK-режим (AI_MOCK=true)."
        )

    return {
        "status": "success",
        "station": station,
        "document_sections": document_sections,
        "validation_errors": {},
        "mode": "mock",
    }


def local_generate(passport_data: dict[str, Any]) -> dict[str, Any]:
    """Generate instruction sections using local Qwen via OpenAI-compatible API."""
    meta = passport_data.get("meta") or {}
    station_name = meta.get("station_name") or "Неизвестная станция"

    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    api_url = os.getenv("AI_API_URL", "http://host.docker.internal:11435/v1")
    api_key = os.getenv("AI_API_KEY", "sk-local-key")
    model_name = os.getenv("QWEN_MODEL_NAME", "qwen2.5:3b")

    ai = StationInstructionAI(
        qdrant_url=qdrant_url,
        api_url=api_url,
        api_key=api_key,
        model_name=model_name
    )

    document_sections: dict[str, str] = {}
    validation_errors: dict[str, str] = {}

    for section in SECTIONS:
        try:
            log.info("Generating section: %s", section)
            document_sections[section] = ai.generate_section(section, passport_data)
        except Exception as exc:
            log.exception("Local AI section failed: %s", section)
            document_sections[section] = f"[ОШИБКА ГЕНЕРАЦИИ: {str(exc)}]"
            validation_errors[section] = str(exc)

    return {
        "status": "success" if not validation_errors else "completed_with_errors",
        "station": station_name,
        "document_sections": document_sections,
        "validation_errors": validation_errors,
        "mode": "local_qwen",
    }


def generate_instruction(passport_data: dict[str, Any]) -> dict[str, Any]:
    """Main entry point: choose generation mode."""
    narrative = _narrative(passport_data)

    # 1. Mock mode (for testing without AI)
    if _force_mock():
        log.info("AI_MOCK=true — deterministic mock generator")
        return mock_generate(passport_data)

    # 2. Local AI mode (default)
    if _use_local_ai():
        try:
            log.info("Using local Qwen via OpenAI-compatible API")
            return local_generate(passport_data)
        except Exception as e:
            log.exception("Local AI failed — falling back to document/facts mode")
            # fall through to fallback modes

    # 3. Document narrative mode (no AI, use uploaded document text)
    if _narrative_substance(narrative):
        log.info(
            "Using document narrative (%s sections, ~%s chars)",
            len(narrative),
            sum(len(str(x.get("text") or "")) for x in narrative),
        )
        return from_narrative(passport_data, narrative)

    # 4. Facts mode (last resort)
    log.info("Using structured facts generator")
    return from_facts(passport_data)


def debug_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)[:500]