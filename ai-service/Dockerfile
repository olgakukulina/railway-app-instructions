# тоже менять
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Lightweight deps for Rabbit/MinIO worker (AI_MOCK=true by default).
# For real GigaChat RAG install requirements.txt instead.
COPY requirements-worker.txt .
RUN pip install --no-cache-dir -r requirements-worker.txt

COPY . .

CMD ["python", "worker.py"]
