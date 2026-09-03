import os
import docx
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from dotenv import load_dotenv

load_dotenv()


COLLECTION_NAME = "station_instructions"
DOCS_DIR = "./reference_docs"

QDRANT_URL = "http://qdrant:6333"

def parse_docx(file_path: str) -> list[Document]:
    doc = docx.Document(file_path)
    documents = []
    current_section = "БЕЗ РАЗДЕЛА"
    current_text = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        is_header = text.isupper() or text.upper().startswith(("РАЗДЕЛ", "ГЛАВА", "ОБЩАЯ ХАРАКТЕРИСТИКА"))
        
        if is_header and len(text) < 150:
            if current_text:
                documents.append(Document(
                    page_content="\n".join(current_text),
                    metadata={"section_name": current_section, "source": os.path.basename(file_path)}
                ))
            current_section = text
            current_text = []
        else:
            current_text.append(text)

    if current_text:
        documents.append(Document(
            page_content="\n".join(current_text),
            metadata={"section_name": current_section, "source": os.path.basename(file_path)}
        ))
    return documents

def main():
    print("Начинаем процесс загрузки референсов в Docker (Qdrant)...") 
    
    if not os.path.exists(DOCS_DIR):
        print(f"Ошибка: Создай папку '{DOCS_DIR}' и положи туда файлы .docx")
        return

    all_chunks = []
    for filename in os.listdir(DOCS_DIR):
        if filename.endswith(".docx"):
            filepath = os.path.join(DOCS_DIR, filename)
            print(f"Парсинг файла: {filename}")
            all_chunks.extend(parse_docx(filepath))

    if not all_chunks:
        return

    print(f"Всего подготовлено фрагментов: {len(all_chunks)}")

    client = QdrantClient(url=QDRANT_URL, timeout=60.0)
    embeddings = HuggingFaceEmbeddings(model_name="cointegrated/rubert-tiny2")

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=312, distance=Distance.COSINE)
        )
        print(f"Создана новая коллекция: {COLLECTION_NAME}")

    print("Отправка векторов в Qwen и сохранение в Docker... (это займет пару минут)")
    QdrantVectorStore.from_documents(
        all_chunks, 
        embeddings, 
        url=QDRANT_URL, 
        collection_name=COLLECTION_NAME,
        force_recreate=True 
    )
    
    print("Загрузка успешно завершена! База знаний готова к работе.")

if __name__ == "__main__":
    main()