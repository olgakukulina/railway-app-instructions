import json
import os
from qdrant_client import QdrantClient
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document

# Подключение к Qdrant
client = QdrantClient(url="http://qdrant:6333")
embeddings = HuggingFaceEmbeddings(model_name="cointegrated/rubert-tiny2")

# Путь к sample_input.json (он в корне проекта)
# Мы будем копировать его в папку document-service
sample_path = "sample_input.json"

if not os.path.exists(sample_path):
    print("Файл sample_input.json не найден!")
    exit(1)

# Загружаем sample_input.json
with open(sample_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Превращаем разделы в документы
documents = []
for section in data["sections"]:
    doc = Document(
        page_content=section["text"],
        metadata={"section_name": section["title"]}
    )
    documents.append(doc)

# Загружаем в Qdrant (с перезаписью)
QdrantVectorStore.from_documents(
    documents,
    embeddings,
    url="http://qdrant:6333",
    collection_name="station_instructions",
    force_recreate=True
)

print(f"Загружено {len(documents)} референсов в Qdrant")