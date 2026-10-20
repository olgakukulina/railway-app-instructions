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


_LATEX_SYMBOLS = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "sim": "~", "equiv": "≡", "infty": "∞",
    "to": "→", "rightarrow": "→", "Rightarrow": "⇒", "leftarrow": "←",
    "sum": "Σ", "prod": "∏", "partial": "∂", "circ": "°", "degree": "°",
    "permil": "‰", "permille": "‰", "lceil": "⌈", "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋",
    "ldots": "…", "cdots": "…", "dots": "…",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "Delta": "Δ",
    "epsilon": "ε", "varepsilon": "ε", "eta": "η", "theta": "θ", "lambda": "λ",
    "mu": "μ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "varphi": "φ", "omega": "ω", "Omega": "Ω",
}
_SUP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUB = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
_SUP_CHARS = set("0123456789+-=()ni")
_SUB_CHARS = set("0123456789+-=()aehijklmnoprstuvx")
_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\[(.+?)\\\]|\\\((.+?)\\\)", re.S)


def _script(base: str, content: str, chars: set[str], table: dict[int, int], mark: str) -> str:
    content = content.strip()
    if content and set(content) <= chars:
        return base + content.translate(table)
    return f"{base}{mark}({content})" if len(content) > 1 else f"{base}{mark}{content}"


def _wrap(part: str) -> str:
    part = part.strip()
    return f"({part})" if re.search(r"[\s+\-−·×/]", part) else part


def _latex_pass(text: str, full: bool) -> str:
    """Один проход замен LaTeX → Unicode. full=True — внутри $…$: ещё и ^x/_x без скобок."""
    group = r"\{([^{}]*)\}"
    for _ in range(10):  # самые вложенные {…} раскрываются первыми
        before = text
        text = re.sub(r"\\[dt]?frac\s*" + group + r"\s*" + group,
                      lambda m: f"{_wrap(m.group(1))}/{_wrap(m.group(2))}", text)
        text = re.sub(r"\\sqrt\s*" + group, lambda m: "√" + _wrap(m.group(1)), text)
        text = re.sub(r"\\(?:text|mathrm|mathbf|mathit|textbf|textit|operatorname|mbox)\s*" + group,
                      r"\1", text)
        text = re.sub(r"(\S?)\^" + group, lambda m: _script(m.group(1), m.group(2), _SUP_CHARS, _SUP, "^"), text)
        text = re.sub(r"(\S?)_" + group, lambda m: _script(m.group(1), m.group(2), _SUB_CHARS, _SUB, "_"), text)
        if text == before:
            break
    text = re.sub(r"\\[dt]?frac\s*(\d)\s*(\d)", r"\1/\2", text)
    text = re.sub(r"\\sqrt\s*(\w)", r"√\1", text)
    if full:
        text = re.sub(r"(\S)\^([\w+\-])", lambda m: _script(m.group(1), m.group(2), _SUP_CHARS, _SUP, "^"), text)
        text = re.sub(r"(\S)_(\w)", lambda m: _script(m.group(1), m.group(2), _SUB_CHARS, _SUB, "_"), text)
    text = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\s*([()\[\]|.]|\\[{}])?",
                  lambda m: (m.group(1) or "").lstrip("\\").replace(".", ""), text)
    text = re.sub(r"\\(?:,|;|:|!|quad|qquad)" + ("|~" if full else ""), " ", text)
    text = re.sub(r"\\([%{}$&#])", r"\1", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda m: _LATEX_SYMBOLS.get(m.group(1), m.group(1)), text)
    return text


def latex_to_text(text: str) -> str:
    """Формулы LaTeX ($…$, \\(…\\), \\[…\\], \\frac, ^{2}) → обычный текст с Unicode."""
    if "\\" not in text and "$" not in text and "^{" not in text and "_{" not in text:
        return text
    text = _MATH_RE.sub(lambda m: _tidy(_latex_pass(next(g for g in m.groups() if g is not None), True)), text)
    return _latex_pass(text, False)


def _tidy(formula: str) -> str:
    formula = formula.replace("{", "").replace("}", "")
    formula = re.sub(r"([(\[⌈⌊]) +| +([)\]⌉⌋])", r"\1\2", formula)
    return re.sub(r" {2,}", " ", formula).strip()


def strip_emphasis(text: str) -> str:
    """Убирает Markdown-выделение (**жирный**, *курсив*, __, _), чтобы assembler не делал bold/italic.
    Одиночная * между операндами формулы (4*i) — это умножение → «·»."""
    text = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"\1", text)
    text = re.sub(r"(?<=[\w)])\s*\*\s*(?=[\w(])", "·", text)
    return re.sub(r"(?m)^\s*#{1,6}\s+", "", text).replace("**", "")


def _clean_ai_text(text: str) -> str:
    """Убираем отсылки к таблицам и оборванные хвосты вроде «Согласно ведомости (»;
    LaTeX → обычный текст, Markdown-выделение — прочь."""
    lines = []
    for line in strip_emphasis(latex_to_text(str(text or ""))).splitlines():
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


def _cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_table(raw: Any) -> dict[str, Any] | None:
    """Приводит таблицу к виду, который примет assembler (Table.from_dict):
    все ячейки — строки, одинаковое число колонок, без пустых строк."""
    if not isinstance(raw, dict):
        return None
    headers = raw.get("headers")
    headers = [_cell(h) for h in headers] if isinstance(headers, list) else []
    rows = [
        [_cell(c) for c in row]
        for row in (raw.get("rows") or [])
        if isinstance(row, list)
    ]
    rows = [row for row in rows if any(row)]
    if not rows:
        return None
    if not any(headers):
        headers = []
    n_cols = max([len(headers)] + [len(row) for row in rows])
    if headers:
        headers += [""] * (n_cols - len(headers))
    rows = [row + [""] * (n_cols - len(row)) for row in rows]
    return {"headers": headers, "rows": rows}


def _with_source_tables(
    appendices: list[Any], source_tables: list[Any]
) -> list[dict[str, Any]]:
    """Нормализует табличные приложения и дописывает в конец все таблицы
    техпаспорта, которых ещё нет среди приложений. Привязки таблица → раздел
    в данных нет, поэтому таблицы идут приложениями."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in appendices:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "table":
            table = normalize_table(item.get("table"))
            if not table:
                continue
            item = {**item, "table": table}
            seen.add(repr((table["headers"], table["rows"])))
        result.append(item)

    for raw in source_tables if isinstance(source_tables, list) else []:
        table = normalize_table(raw)
        if not table:
            continue
        key = repr((table["headers"], table["rows"]))
        if key in seen:
            continue
        seen.add(key)
        number = _cell(raw.get("number"))
        title = _cell(raw.get("title")) or (f"Таблица {number}" if number else "Таблица")
        result.append({"title": title, "type": "table", "table": table})
    return result


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

    appendices = _with_source_tables(
        ai_result.get("appendices") or [],
        passport_data.get("source_tables") or [],
    )

    return {
        "document_id": task_id,
        "station_name": station_name,
        "region": region,
        "organization": organization,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
        "appendices": appendices,
    }