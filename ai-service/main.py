"""FastAPI server for generating station instructions using local Qwen model."""

import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
from ai_engine import StationInstructionAI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Генератор Инструкций Станций", version="2.0")

# Берём из .env или используем значения по умолчанию
API_URL = os.getenv("AI_API_URL", "http://host.docker.internal:11435/v1")
API_KEY = os.getenv("AI_API_KEY", "sk-local-key")
MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen3-8b")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")

class GenerateRequest(BaseModel):
    passport_data: Dict[str, Any]


@app.post("/api/v1/generate")
def generate_instruction(request: GenerateRequest):
    meta_data = request.passport_data.get("meta", {})
    station_name = meta_data.get("station_name", "Неизвестная станция")

    # Создаём AI-движок с локальной моделью
    ai = StationInstructionAI(
        qdrant_url=QDRANT_URL,
        api_url=API_URL,
        api_key=API_KEY,
        model_name=MODEL_NAME
    )

    sections_to_generate = [
        "ОБЩАЯ ХАРАКТЕРИСТИКА ПУТИ НЕОБЩЕГО ПОЛЬЗОВАНИЯ",
        "ПОРЯДОК ПОДАЧИ И УБОРКИ ВАГОНОВ",
        "МАНЕВРОВАЯ РАБОТА",
        "ЗАКРЕПЛЕНИЕ ВАГОНОВ",
        "ТЕХНИКА БЕЗОПАСНОСТИ",
    ]

    document_sections = {}
    validation_errors = {}

    for section in sections_to_generate:
        print(f"Генерация раздела: {section}...")
        try:
            text = ai.generate_section(section, request.passport_data)
            document_sections[section] = text
        except Exception as e:
            print(f"Ошибка в разделе {section}: {str(e)}")
            document_sections[section] = f"[ОШИБКА ГЕНЕРАЦИИ: {str(e)}]"
            validation_errors[section] = str(e)

    response = {
        "status": "success" if not validation_errors else "completed_with_errors",
        "station": station_name,
        "document_sections": document_sections,
        "validation_errors": validation_errors,
    }

    return response


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)