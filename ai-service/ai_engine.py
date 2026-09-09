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

SYSTEM_PROMPT = """Ты — ведущий инженер-технолог железнодорожного транспорта.

Напиши ОФИЦИАЛЬНЫЙ ТЕКСТ раздела "{section_name}" для местной инструкции станции.

ПРАВИЛА:
1. Пиши СВЯЗНЫЙ, ГРАМОТНЫЙ ТЕКСТ, а не список фактов.
2. Используй данные из техпаспорта КАК ИСХОДНЫЕ ФАКТЫ.
3. НЕ КОПИРУЙ данные дословно, переформулируй.
4. НЕ ИСПОЛЬЗУЙ Markdown и списки.
5. НЕ ПИШИ заголовок раздела, слово «ИНСТРУКЦИЯ», нумерацию «РАЗДЕЛ N» и вообще
   любое название документа — их добавляет система автоматически. Начинай сразу
   с содержательного текста раздела.
6. НЕ ПЕРЕПИСЫВАЙ построчно таблицы, перечни путей, пикетов (вида «пк00+33.54»)
   и номера стрелочных переводов — обобщи их одним-двумя предложениями своими
   словами, подробные данные уже вынесены в отдельные таблицы документа.
7. Ответ должен содержать ТОЛЬКО связный текст раздела "{section_name}", без
   упоминания других разделов инструкции.

ДАННЫЕ ИЗ ТЕХПАСПОРТА (используй как факты, не копируй построчно):
{passport_data}

ПРИМЕР СТИЛЯ (только стиль, не копировать содержание):
{references}
"""


class StationInstructionAI:
    def __init__(
            self,
            qdrant_url: str = "http://qdrant:6333",
            api_url: str = "http://host.docker.internal:11435/v1",
            api_key: str = "sk-local-key",
            model_name: str = "qwen2.5:3b"
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
            timeout=120.0,
            max_retries=1,
        )

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        return text.strip()

    _PIKET_RE = re.compile(r'пк\s*\d+\+\d+', re.IGNORECASE)

    def _looks_like_table_row(self, text: str) -> bool:
        """Отсекаем сырые строки таблиц (пикеты, номера путей) — их не нужно
        скармливать модели дословно, она всё равно просто перепишет их как есть."""
        if len(self._PIKET_RE.findall(text)) >= 2:
            return True
        digit_ratio = sum(ch.isdigit() for ch in text) / max(len(text), 1)
        return digit_ratio > 0.3

    def _extract_important_facts(self, passport_data: dict, section_name: str, max_chars: int = 2500) -> str:
        parts = []
        seen = set()

        meta = passport_data.get("meta", {})
        if isinstance(meta, dict):
            for key, value in meta.items():
                if value and isinstance(value, str):
                    text = f"{key}: {value}"
                    if text not in seen:
                        parts.append(text)
                        seen.add(text)

        general = passport_data.get("general", {})
        if isinstance(general, dict):
            for key, value in general.items():
                if value and str(value).strip():
                    text = f"{key}: {value}"
                    if text not in seen:
                        parts.append(text)
                        seen.add(text)

        sections = passport_data.get("sections", [])
        for section in sections:
            if not isinstance(section, dict):
                continue
            text = section.get("text", "")
            if not text or not isinstance(text, str):
                continue

            text = self._clean_text(text)
            if len(text) < 20:
                continue

            sentences = re.split(r'[.!?]\s*', text)
            for sentence in sentences:
                sentence = self._clean_text(sentence)
                if len(sentence) < 20 or self._looks_like_table_row(sentence):
                    continue

                if sentence not in seen:
                    if len(sentence) > 500:
                        sentence = sentence[:500] + "..."
                    parts.append(sentence)
                    seen.add(sentence)

                    if len(" ".join(parts)) > max_chars:
                        break
            if len(" ".join(parts)) > max_chars:
                break

        if len(" ".join(parts)) < 500:
            narrative = passport_data.get("source_narrative", [])
            for item in narrative:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text and isinstance(text, str):
                        text = self._clean_text(text)
                        if len(text) > 30 and not self._looks_like_table_row(text) and text not in seen:
                            parts.append(text[:500])
                            seen.add(text)
                            if len(" ".join(parts)) > max_chars:
                                break
                if len(" ".join(parts)) > max_chars:
                    break

        result = ". ".join(parts)
        result = self._clean_text(result)

        if len(result) > max_chars:
            result = result[:max_chars] + "..."

        log.info(f"Извлечено фактов: {len(parts)} шт, {len(result)} символов (~{len(result) // 4} токенов)")
        return result if result else "Данные техпаспорта отсутствуют."

    def _retrieve_references(self, section_name: str) -> str:
        try:
            if not self.qdrant.collection_exists(self.collection_name):
                return ""

            filter_obj = models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.section_name",
                        match=models.MatchValue(value=section_name)
                    )
                ]
            )

            results = self.vector_store.similarity_search(
                query=section_name,
                k=1,
                filter=filter_obj
            )

            if results:
                return self._clean_text(results[0].page_content[:300])
            return ""

        except Exception as e:
            log.warning(f"Failed to retrieve references: {e}")
            return ""

    def generate_section(self, section_name: str, passport_data: dict) -> str:
        try:
            log.info(f"=== passport_data keys: {list(passport_data.keys())} ===")
            log.info(f"=== sections count: {len(passport_data.get('sections', []))} ===")

            passport_context = self._extract_important_facts(passport_data, section_name, max_chars=2500)
            references = self._retrieve_references(section_name)

            prompt = SYSTEM_PROMPT.format(
                section_name=section_name,
                passport_data=passport_context,
                references=references if references else "Железнодорожный путь принадлежит станции."
            )

            if len(prompt) > 8000:
                prompt = prompt[:8000] + "..."

            log.info(f"Промпт: {len(prompt)} символов (~{len(prompt) // 4} токенов)")

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Напиши раздел '{section_name}' для инструкции станции."}
                ],
                temperature=0.4,
                max_tokens=600,
                top_p=0.9,
            )

            log.info(f"=== ВСЕГО ТОКЕНОВ: {response.usage.total_tokens} ===")
            log.info(f"=== ПРОМПТ ТОКЕНОВ: {response.usage.prompt_tokens} ===")
            log.info(f"=== ОТВЕТ ТОКЕНОВ: {response.usage.completion_tokens} ===")

            result = response.choices[0].message.content
            if not result or len(result.strip()) < 10:
                return f"Не удалось сгенерировать раздел '{section_name}'."

            return result.strip()

        except Exception as e:
            log.exception(f"Ошибка: {e}")
            return f"[ОШИБКА: {str(e)}]"