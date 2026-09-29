import json
import os
import logging
import re
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

DEBUG_NO_LLM = os.getenv("DEBUG_NO_LLM", "false").lower() in ("1", "true", "yes")


MAX_NARRATIVE_CHARS = 5000
MAX_REFERENCE_CHARS = 2000
MAX_TABLE_ROWS = 100
MAX_FACTS_CHARS = 20000
MAX_OUTPUT_TOKENS = 4000

STUB_NO_DATA = (
    "Фактов в техпаспорте недостаточно для генерации данного подраздела. "
    "Требуется ручное заполнение."
)

TYPICAL_NORMS = """- Максимальная скорость движения маневрового состава по пути необщего пользования: 15 км/ч.
- Скорость при движении вагонами вперёд: не более 3 км/ч.
- Скорость при осаживании вагонов: не более 3 км/ч.
- Скорость при проследовании негабаритных и опасных мест: не более 3 км/ч.
- Остановка маневрового состава перед сбрасывающим башмаком: не менее 5 метров.
- Проверка действия автотормозов: по двум хвостовым вагонам.
- Закрепление вагонов: тормозными башмаками с накатом обода колеса на полоз башмака.
- Управление маневровым локомотивом: по команде составителя поездов по радиосвязи.
- Связь с дежурным по станции: по радиосвязи или телефону.
- Сбрасывающий башмак в нормальном положении: «на сброс», запирается на навесной замок.
- Порядок выезда на путь необщего пользования: по разрешающему показанию светофора, при неисправности — по устному разрешению ДСП.
- Составитель поездов при движении вагонами вперёд находится на первой по ходу движения подножке вагона, следит за свободностью пути.
- Состав маневровой бригады: машинист, помощник машиниста, составитель поездов.
"""

JUNK_COLUMNS = {"дата внесения изменений", "ф.и.о", "ф.и.о.", "подпись",
                "ф.и.о. должность", "ф.и.о. должность лица внесшего изменение",
                "ф.и.о должность лица внесшего изменения",
                "ф.и.о. должность внесшего изменения"}

SECTION_STRUCTURE = {
    "ОБЩАЯ ХАРАКТЕРИСТИКА ПУТИ НЕОБЩЕГО ПОЛЬЗОВАНИЯ": [
        ("1.1", "Принадлежность железнодорожного пути необщего пользования"),
        ("1.2", "Обслуживание локомотивами"),
        ("1.3", "Место примыкания железнодорожного пути необщего пользования к станции и его границы"),
        ("1.4", "Наличие предохранительного устройства"),
        ("1.5", "Характеристика путевого развития и стрелочного хозяйства"),
        ("1.6", "Допускаемые скорости движения"),
        ("1.7", "Характеристика устройств СЦБ"),
        ("1.8", "Характеристика грузового хозяйства"),
        ("1.9", "Ответственные лица"),
    ],
    "ПОРЯДОК ПОДАЧИ И УБОРКИ ВАГОНОВ": [
        ("2.1", "Порядок обслуживания локомотивами"),
        ("2.2", "Величина максимального состава"),
        ("2.3", "Порядок включения автотормозов"),
        ("2.4", "Порядок согласования движения составов"),
        ("2.5", "Порядок выезда состава со станции"),
        ("2.6", "Порядок следования состава на путь необщего пользования"),
        ("2.7", "Порядок въезда состава на путь необщего пользования"),
        ("2.8", "Порядок обратного следования состава"),
        ("2.9", "Порядок въезда состава на станцию"),
    ],
    "МАНЕВРОВАЯ РАБОТА": [
        ("3.1", "Порядок выполнения маневровой работы"),
        ("3.2", "Порядок расстановки вагонов под грузовые операции"),
        ("3.3", "Порядок приготовления маневровых маршрутов"),
        ("3.4", "Особенности производства маневров в местных условиях"),
    ],
    "ЗАКРЕПЛЕНИЕ ВАГОНОВ": [
        ("4.1", "Порядок и нормы закрепления вагонов"),
        ("4.2", "Регламент выполнения операций по закреплению"),
        ("4.3", "Наличие, порядок хранения и клеймение тормозных башмаков"),
        ("4.4", "Ответственность"),
    ],
    "ТЕХНИКА БЕЗОПАСНОСТИ": [
        ("5.1", "Обязанности работников"),
        ("5.2", "Местные особенности"),
        ("5.3", "Ответственность"),
    ],
}

SUBSECTION_HINTS = {
    "1.1": ["Укажи название предприятия-владельца пути", "Укажи номер пути", "Укажи, на чьём балансе находится путь"],
    "1.2": ["Укажи, кто производит маневровую работу", "Укажи серию локомотива", "Укажи состав маневровой бригады", "Укажи наличие/отсутствие собственного локомотива"],
    "1.3": ["Укажи, к какому пути/станции примыкает путь", "Укажи номер стрелочного перевода", "Укажи границы пути", "Укажи пикетажные отметки границ"],
    "1.4": ["Укажи наличие предохранительных тупиков или сбрасывающих башмаков", "Укажи номера предохранительных устройств", "Укажи их расположение (ПК)", "Опиши порядок их использования"],
    "1.5": ["Укажи полную длину пути", "Укажи полезную длину пути", "Укажи тип рельсов", "Укажи максимальный уклон пути", "Укажи минимальный радиус кривой"],
    "1.6": ["Укажи максимальную скорость движения", "Укажи скорость при движении вагонами вперёд", "Укажи скорость при осаживании", "Укажи скорость при проследовании негабаритных мест"],
    "1.7": ["Укажи, имеются ли устройства СЦБ", "Укажи, имеются ли распорядительные посты", "Опиши, как осуществляется связь с дежурным"],
    "1.8": ["Укажи количество грузовых фронтов", "Укажи расположение каждого фронта", "Укажи вместимость каждого фронта", "Укажи средства механизации"],
    "1.9": ["Укажи, кто осуществляет контроль безопасности", "Опиши, как устанавливается список ответственных лиц", "Укажи, кто отвечает за техническое состояние пути"],
    "2.1": ["Укажи, каким локомотивом производится подача/уборка", "Укажи, кто отвечает за передвижение", "Укажи, запрещено ли использование других подвижных единиц"],
    "2.2": ["Укажи максимальную величину состава", "Укажи, чем ограничена величина состава", "Укажи, кто определяет вес маневрового состава"],
    "2.3": ["Опиши порядок включения автотормозов", "Укажи, сколько хвостовых вагонов проверяется", "Укажи, кто отвечает за включение автотормозов"],
    "2.4": ["Опиши порядок согласования маневровых операций", "Укажи, кто участвует в согласовании", "Опиши порядок передачи информации при неисправности связи"],
    "2.5": ["Укажи, кто выдаёт ключ от сбрасывающего башмака", "Укажи, по какому показанию светофора производится выезд", "Опиши действия при невозможности открыть светофор"],
    "2.6": ["Опиши порядок следования состава на путь", "Укажи, где находится составитель поездов", "Опиши, какие команды передаются машинисту"],
    "2.7": ["Опиши меры, принимаемые ответственным работником перед въездом", "Укажи расстояние остановки состава перед башмаком", "Опиши порядок установки сбрасывающего башмака"],
    "2.8": ["Опиши порядок уборки вагонов", "Укажи, кто проверяет габарит погруженного груза", "Укажи, что докладывает составитель поездов дежурному"],
    "2.9": ["Укажи, по какому показанию светофора производится въезд", "Опиши действия при неисправности СЦБ", "Укажи, кто даёт разрешение на въезд"],
    "3.1": ["Укажи, кто отвечает за передвижение маневрового состава", "Укажи, кто распоряжается маневрами по расстановке вагонов", "Укажи, разрешены ли маневры двумя локомотивами"],
    "3.2": ["Опиши порядок расстановки вагонов", "Укажи, что запрещается при передвижении вагонов", "Укажи, что проверяет составитель перед началом маневров"],
    "3.3": ["Опиши порядок приготовления маневровых маршрутов", "Опиши порядок передачи информации о готовности маршрута", "Опиши действия при неисправности радиосвязи"],
    "3.4": ["Укажи, что запрещается работникам предприятия", "Опиши порядок маневров при неблагоприятных погодных условиях", "Опиши действия при нарушении габарита"],
    "4.1": ["Укажи, где указаны нормы закрепления", "Укажи, кто производит закрепление вагонов", "Опиши формулу расчёта норм закрепления"],
    "4.2": ["Укажи, что докладывает составитель поездов о закреплении", "Укажи, какая информация вносится в книгу закрепления", "Опиши порядок уборки тормозных башмаков"],
    "4.3": ["Укажи количество тормозных башмаков у владельца", "Укажи, где они хранятся", "Перечисли неисправности башмаков"],
    "4.4": ["Укажи, кто отвечает за правильное закрепление вагонов", "Укажи, кто несёт ответственность после отцепки локомотива", "Опиши действия при выявлении нарушений"],
    "5.1": ["Перечисли правила охраны труда", "Опиши меры безопасности при закреплении вагонов", "Опиши порядок сцепления и расцепления вагонов"],
    "5.2": ["Перечисли негабаритные и опасные места на пути", "Опиши, как обозначаются негабаритные места", "Опиши порядок проследования технологических проездов"],
    "5.3": ["Перечисли требования, которые обеспечивает владелец пути", "Укажи, кто отвечает за безопасные условия труда", "Перечисли требования по освещению и содержанию пути"],
}

SUBSECTION_TARGET_CHARS = {
    "1.1": 200,
    "1.2": 1000,
    "1.3": 500,
    "1.4": 2000,
    "1.5": 800,
    "1.6": 800,
    "1.7": 300,
    "1.8": 2500,
    "1.9": 1200,
    "2.1": 300,
    "2.2": 500,
    "2.3": 700,
    "2.4": 900,
    "2.5": 600,
    "2.6": 1800,
    "2.7": 3000,
    "2.8": 1200,
    "2.9": 400,
    "3.1": 700,
    "3.2": 1200,
    "3.3": 300,
    "3.4": 600,
    "4.1": 1200,
    "4.2": 2000,
    "4.3": 1800,
    "4.4": 800,
    "5.1": 1500,
    "5.2": 1800,
    "5.3": 800,
}

SUBSECTION_KEYWORDS = {
    "1.1": {"keys": ["company_name", "owner", "принадлеж", "баланс", "владелец"], "tables": [], "requires_data": True},
    "1.2": {"keys": ["locomotive", "локомотив", "маневров", "service_order", "подача", "уборка", "тэм"], "tables": [], "requires_data": True},
    "1.3": {"keys": ["junction", "примыкан", "границ", "boundary", "стрелочн", "пикет"], "tables": [], "requires_data": True},
    "1.4": {"keys": ["предохранит", "тупик", "сбрасывающ", "башмак", "улавливающ"], "tables": [], "requires_data": True},
    "1.5": {"keys": ["длина", "length", "рельс", "rails", "уклон", "радиус", "стрелочн", "шпал", "балласт"], "tables": ["длина", "рельс", "ведомость путей", "стрелочн", "шпал"], "requires_data": True},
    "1.6": {"keys": ["скорост", "speed", "км/ч"], "tables": [], "requires_data": False},
    "1.7": {"keys": ["сцб", "сигнализац", "централизац", "блокировк", "распорядительн", "связь"], "tables": [], "requires_data": False},
    "1.8": {"keys": ["грузов", "фронт", "front", "площадк", "рамп", "вместим", "механизац", "cargo"], "tables": ["фронт", "грузов", "вместим"], "requires_data": True},
    "1.9": {"keys": ["ответствен", "контрол", "безопасн"], "tables": [], "requires_data": False},
    "2.1": {"keys": ["locomotive", "локомотив", "подача", "уборка", "service_order"], "tables": [], "requires_data": True},
    "2.2": {"keys": ["состав", "вагон", "вес", "осей", "маневровый состав"], "tables": [], "requires_data": False},
    "2.3": {"keys": ["автотормоз", "тормоз", "опробован"], "tables": [], "requires_data": False},
    "2.4": {"keys": ["согласован", "связь", "радиосвязь"], "tables": [], "requires_data": False},
    "2.5": {"keys": ["выезд", "светофор", "ключ", "башмак"], "tables": [], "requires_data": False},
    "2.6": {"keys": ["следован", "порядок", "составитель"], "tables": [], "requires_data": False},
    "2.7": {"keys": ["въезд", "башмак", "остановк"], "tables": [], "requires_data": False},
    "2.8": {"keys": ["обратн", "уборк", "габарит"], "tables": [], "requires_data": False},
    "2.9": {"keys": ["въезд", "станц", "светофор", "сцб"], "tables": [], "requires_data": False},
    "3.1": {"keys": ["маневров", "передвижен", "локомотив"], "tables": [], "requires_data": False},
    "3.2": {"keys": ["расстановк", "погрузк", "выгрузк"], "tables": [], "requires_data": False},
    "3.3": {"keys": ["маршрут", "приготовлен"], "tables": [], "requires_data": False},
    "3.4": {"keys": ["особенност", "погодн", "габарит"], "tables": [], "requires_data": False},
    "4.1": {"keys": ["закрепл", "противоугон", "башмак", "норм"], "tables": ["закрепл", "противоугон", "башмак"], "requires_data": True},
    "4.2": {"keys": ["закрепл", "книга", "доклад"], "tables": ["закрепл", "башмак"], "requires_data": False},
    "4.3": {"keys": ["башмак", "хранен", "клейм"], "tables": ["башмак", "закрепл"], "requires_data": False},
    "4.4": {"keys": ["ответствен", "закрепл"], "tables": [], "requires_data": False},
    "5.1": {"keys": ["охрана труда", "безопасн", "сцепл", "расцепл"], "tables": [], "requires_data": False},
    "5.2": {"keys": ["негабарит", "опасн", "проезд"], "tables": [], "requires_data": False},
    "5.3": {"keys": ["ответствен", "освещен", "содержан"], "tables": [], "requires_data": False},
}


class StationInstructionAI:
    def __init__(
            self,
            qdrant_url: str = "http://qdrant:6333",
            api_url: str = "http://host.docker.internal:11435/v1",
            api_key: str = "sk-local-key",
            model_name: str = "qwen3-8b"
    ):
        self.collection_name = "station_instructions"
        self.model_name = model_name

        self.qdrant = QdrantClient(url=qdrant_url, timeout=30.0)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="cointegrated/rubert-tiny2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        self.vector_store = QdrantVectorStore(
            client=self.qdrant,
            collection_name=self.collection_name,
            embedding=self.embeddings
        )

        self.client = OpenAI(
            base_url=api_url,
            api_key=api_key,
            timeout=300.0,
            max_retries=1,
        )

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        return text.strip()

    def _extract_structured_facts(self, passport_data: dict) -> dict:
        facts = {
            "meta": {},
            "general": {},
            "narrative": [],
            "tables_length": [],
            "tables_rails": [],
            "tables_cargo": [],
            "tables_brakes": [],
            "all_tables": [],
        }

        meta = passport_data.get("meta", {})
        if isinstance(meta, dict):
            for k, v in meta.items():
                if v:
                    facts["meta"][k] = v

        for item in passport_data.get("source_narrative", []):
            if isinstance(item, dict):
                title = str(item.get("title") or "").strip()
                text = str(item.get("text") or "").strip()
                if text:
                    facts["narrative"].append({"title": title, "text": text})

        sec1 = passport_data.get("section_1_general_characteristics") or {}
        if isinstance(sec1, dict):
            for k, v in sec1.items():
                if isinstance(v, dict) and v.get("available"):
                    facts["general"][k] = v.get("data")
                elif v:
                    facts["general"][k] = v

        for table in passport_data.get("source_tables", []):
            if not isinstance(table, dict):
                continue
            title = str(table.get("title", "")).lower()
            record = {
                "title": table.get("title"),
                "headers": table.get("headers", []),
                "rows": table.get("rows", []),
            }
            facts["all_tables"].append(record)

            if "длина" in title or "ведомость путей" in title:
                facts["tables_length"].append(record)
            elif "рельс" in title:
                facts["tables_rails"].append(record)
            elif "грузов" in title or "фронт" in title:
                facts["tables_cargo"].append(record)
            elif "башмак" in title or "закрепл" in title or "противоугон" in title:
                facts["tables_brakes"].append(record)

        return facts

    def _render_table(self, table: dict) -> str:
        headers = table.get("headers") or []
        rows = table.get("rows") or []

        keep_idx = []
        for i, h in enumerate(headers):
            h_norm = str(h).strip().lower().rstrip(":")
            if h_norm in JUNK_COLUMNS:
                continue
            if "подпись" in h_norm or "ф.и.о" in h_norm:
                continue
            if "дата внесения" in h_norm:
                continue
            keep_idx.append(i)

        lines = [f"--- {table.get('title', 'Без названия')} ---"]
        if headers and keep_idx:
            lines.append(" | ".join(str(headers[i]) for i in keep_idx))
        for row in rows[:MAX_TABLE_ROWS]:
            if isinstance(row, list):
                if keep_idx:
                    lines.append(" | ".join(str(row[i]) for i in keep_idx if i < len(row)))
                else:
                    lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)

    def _iter_leaves(self, data, prefix=""):
        if isinstance(data, dict):
            for k, v in data.items():
                yield from self._iter_leaves(v, f"{prefix}.{k}" if prefix else str(k))
        elif isinstance(data, list):
            for i, v in enumerate(data):
                yield from self._iter_leaves(v, f"{prefix}[{i}]")
        else:
            yield prefix, data

    def _facts_for_subsection(self, facts: dict, subsection_num: str) -> str:
        cfg = SUBSECTION_KEYWORDS.get(subsection_num, {})
        keys_lower = [k.lower() for k in cfg.get("keys", [])]
        table_kw = [k.lower() for k in cfg.get("tables", [])]

        if not keys_lower and not table_kw:
            return ""
        parts = []
        for source_name, source in (("meta", facts.get("meta", {})),
                                    ("general", facts.get("general", {}))):
            for path, value in self._iter_leaves(source):
                last = path.split(".")[-1].lower()
                value_str = (
                    str(value) if not isinstance(value, (dict, list))
                    else json.dumps(value, ensure_ascii=False)
                )
                if any(kw in last for kw in keys_lower) or any(kw in value_str.lower() for kw in keys_lower):
                    if isinstance(value, (dict, list)):
                        parts.append(f"[{source_name}.{path}]\n{json.dumps(value, ensure_ascii=False)}")
                    else:
                        parts.append(f"[{source_name}.{path}]: {value}")
        for item in facts.get("narrative", []):
            text = item.get("text", "")
            if any(kw in text.lower() for kw in keys_lower):
                parts.append(f"[текст техпаспорта]:\n{text[:MAX_NARRATIVE_CHARS]}")
        if table_kw:
            for t in facts.get("all_tables", []):
                title = str(t.get("title", "")).lower()
                if any(kw in title for kw in table_kw):
                    parts.append(self._render_table(t))

        result = "\n\n".join(parts)
        if len(result) > MAX_FACTS_CHARS:
            result = result[:MAX_FACTS_CHARS]
        return result

    def _retrieve_references(self, subsection_key: str) -> str:
        try:
            docs = self.vector_store.similarity_search(subsection_key, k=1)
            if not docs:
                return ""
            ref = docs[0].page_content.strip()[:MAX_REFERENCE_CHARS]
            log.info(f"=== [ОТЛАДКА] Референс найден: {len(ref)} символов ===")
            return ref
        except Exception as e:
            log.warning(f"Не удалось получить референс для '{subsection_key}': {e}")
            return ""

    def _dedupe_lines(self, text: str) -> str:
        lines = text.split("\n")
        seen = set()
        result = []
        for line in lines:
            norm = line.strip().lower()
            if not norm:
                result.append(line)
                continue
            if norm in seen:
                continue
            seen.add(norm)
            result.append(line)
        return "\n".join(result)

    def _generate_subsection(self, section_name: str, subsection_num: str,
                             subsection_title: str, facts_text: str) -> str:
        hints = SUBSECTION_HINTS.get(subsection_num, [])
        hints_text = "\n".join(f"- {h}" for h in hints)
        reference = self._retrieve_references(f"{subsection_num} {subsection_title}")
        reference_block = ""
        if reference:
            reference_block = (
                "\nПРИМЕР СТИЛЯ И СТРУКТУРЫ (факты из этого блока использовать ЗАПРЕЩЕНО,\n"
                "он нужен только чтобы понять, каким языком и как структурировать текст):\n"
                f"{reference}\n"
            )

        cfg = SUBSECTION_KEYWORDS.get(subsection_num, {})
        requires_data = cfg.get("requires_data", True)
        has_data = bool(facts_text.strip())
        if not has_data and requires_data:
            return STUB_NO_DATA
        target = SUBSECTION_TARGET_CHARS.get(subsection_num, 800)
        min_chars = max(150, int(target * 0.8))
        max_chars = int(target * 1.2)

        if has_data:
            data_block = f"ДАННЫЕ ИЗ ТЕХПАСПОРТА:\n{facts_text}"
        else:
            data_block = "ДАННЫЕ ИЗ ТЕХПАСПОРТА: отсутствуют."

        prompt = f"""Напиши подраздел {subsection_num} "{subsection_title}" инструкции по эксплуатации железнодорожного пути необщего пользования.
{reference_block}
ОТРАЗИ:
{hints_text}

{data_block}

ТИПОВЫЕ НОРМАТИВНЫЕ ЗНАЧЕНИЯ (можно использовать, если в ДАННЫХ нет конкретных):
{TYPICAL_NORMS}

ТРЕБОВАНИЯ:
- Объём: {min_chars}-{max_chars} символов. Пиши развёрнуто в этих рамках.
- Официальный технический язык, как в нормативном документе.
- ЗАПРЕЩЕНО: выдумывать номера путей, номера стрелочных переводов, номера тупиков, пикеты, названия организаций (типа ООО «ТрансЛогистик»). Используй только то, что есть в ДАННЫХ.
- РАЗРЕШЕНО: использовать типовые нормативные значения из блока выше, раскрывать общий порядок действий.
- НЕ повторяй один и тот же абзац дважды. Если нечего добавить — заканчивай.
- Не повторяй заголовок подраздела в начале текста.

ТЕКСТ ПОДРАЗДЕЛА {subsection_num}:"""

        log.info(f"=== [ОТЛАДКА] Подраздел {subsection_num}: {subsection_title} ===")
        log.info(f"=== [ОТЛАДКА] facts_text: {len(facts_text)} символов ===")
        log.info(f"=== [ОТЛАДКА] reference: {len(reference)} символов ===")
        log.info(f"=== [ОТЛАДКА] target_chars: {target} (min={min_chars}, max={max_chars}) ===")
        log.info(f"=== [ОТЛАДКА] Промпт: {len(prompt)} символов ===")
        log.info("=" * 60)

        if DEBUG_NO_LLM:
            return (f"[ОТЛАДКА] facts_text={len(facts_text)}, "
                    f"reference={len(reference)}, prompt={len(prompt)}, "
                    f"target={target}.")

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content":
                        "Ты пишешь официальные инструкции для железнодорожных путей необщего пользования. "
                        "Используй ТОЛЬКО факты из блока ДАННЫЕ ИЗ ТЕХПАСПОРТА. "
                        "Если данных нет — используй типовые нормативные значения из блока выше. "
                        "Никогда не выдумывай номера путей, пикеты, названия организаций. "
                        "Не повторяй один и тот же абзац дважды. Не зацикливайся."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=MAX_OUTPUT_TOKENS,
                top_p=0.9,
                frequency_penalty=0.5,
                presence_penalty=0.3,
            )
            if getattr(response, "usage", None):
                log.info(
                    f"=== [ТОКЕНЫ] {subsection_num}: "
                    f"prompt={response.usage.prompt_tokens}, "
                    f"completion={response.usage.completion_tokens}, "
                    f"total={response.usage.total_tokens} ==="
                )

            result = response.choices[0].message.content
            if not result:
                return ""

            result = self._clean_text(result)
            return self._postprocess_text(result)
        except Exception as e:
            log.exception(f"Ошибка генерации подраздела {subsection_num}: {e}")
            return ""

    def _postprocess_text(self, text: str) -> str:
        if not text:
            return ""
        text = self._dedupe_lines(text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        return text.strip()

    def generate_section(self, section_name: str, passport_data: dict) -> str:
        try:
            log.info(f"=== Генерация раздела: {section_name} ===")
            facts = self._extract_structured_facts(passport_data)

            log.info(f"=== [ОТЛАДКА] meta: {facts['meta']} ===")
            log.info(f"=== [ОТЛАДКА] general keys: {list(facts['general'].keys())} ===")
            log.info(f"=== [ОТЛАДКА] narrative: {len(facts['narrative'])} ===")
            log.info(f"=== [ОТЛАДКА] all_tables: {len(facts['all_tables'])} ===")

            subsections = SECTION_STRUCTURE.get(section_name, [("1.1", "Общие сведения")])
            log.info(f"Подразделов: {len(subsections)}")

            parts = []
            for num, title in subsections:
                log.info(f"  Генерация подраздела {num}: {title}")
                facts_text = self._facts_for_subsection(facts, num)

                part = self._generate_subsection(
                    section_name=section_name,
                    subsection_num=num,
                    subsection_title=title,
                    facts_text=facts_text,
                )

                if part and len(part) > 50:
                    parts.append(f"{num}. {title}\n\n{part}")
                    log.info(f"    Подраздел {num}: {len(part)} символов")
                else:
                    log.warning(f"    Подраздел {num}: пустой ответ")
                    parts.append(f"{num}. {title}\n\n{STUB_NO_DATA}")

            result = "\n\n".join(parts)
            log.info(f"=== Раздел '{section_name}' готов: {len(result)} символов ===")
            return result

        except Exception as e:
            log.exception(f"Ошибка генерации раздела {section_name}: {e}")
            return f"[ОШИБКА: {str(e)}]"