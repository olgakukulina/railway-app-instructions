~~# Railway AI Platform

Платформа автоматической генерации **технологических инструкций** по железнодорожному пути необщего пользования на основе **техпаспорта** станции.

Пайплайн:

```
Frontend → Gateway → (RabbitMQ) → Document → AI (GigaChat) → Assembler → PDF
                         ↕
                      MinIO + PostgreSQL
```

Статусы задачи: `CREATED → PARSING → PARSED → GENERATING → GENERATED → ASSEMBLING → COMPLETED | FAILED`.

---

## Что нужно заранее

| Требование | Зачем |
|------------|--------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) (или Docker Engine + Compose v2) | Поднять все сервисы |
| ~8 GB RAM свободно | LibreOffice + Java + Python-воркеры |
| Аккаунт [Sber Studio / GigaChat API](https://developers.sber.ru/studio) | Реальная генерация текста (иначе будет режим без LLM) |
| Git | Клонирование репозитория |

Опционально: Node.js 22+ — только если хотите запускать frontend локально через Vite, а не из Docker.

---

## Быстрый старт (всё в Docker)

### 1. Клонировать репозиторий

```bash
git clone https://github.com/OneMouseClick/railway_app_instructions.git
cd railway_app_instructions
git checkout main
```

## 2. Запуск сервера с локальным ИИ через llama.cpp

1. Скачай [llama-b10734-bin-win-vulkan-x64](https://github.com/ggerganov/llama.cpp/releases)

2. Скачай модель в формате GGUF:
   [Qwen3-8B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/blob/main/Qwen3VL-8B-Instruct-Q4_K_M.gguf)

3. Запусти сервер:
```cmd
cd C:\llama (или любой другой путь)
llama-server.exe -m models\Qwen3-8B-Q4_K_M.gguf -c 4096 -ngl 99 -p 11435
```
### 3. Поднять платформу

Из корня репозитория:

```bash
docker compose --env-file .env up -d --build
```

Первый запуск может занять несколько минут (сборка gateway / LibreOffice в образах).

Проверка, что контейнеры живы:

```bash
docker compose ps
```

Ожидаются: `railway-gateway` (healthy), `document-service`, `ai-service`, `assembler-service`, `frontend`, `postgres`, `rabbitmq`, `minio`.

### 4. Открыть UI и зарегистрироваться

| Что | URL |
|-----|-----|
| Frontend | http://localhost:5173 |
| Gateway Swagger | http://localhost:8080/swagger-ui.html |
| RabbitMQ UI | http://localhost:15672 (`railway` / `railway_secret`) |
| MinIO UI | http://localhost:9001 (`minioadmin` / `minioadmin`) |

1. Откройте http://localhost:5173  
2. Зарегистрируйте пользователя (или через Swagger: `POST /api/v1/auth/register`)  
3. Войдите  
4. Загрузите техпаспорт (`.doc` / `.docx` / `.pdf`)  
5. Дождитесь статуса **COMPLETED**  
6. Нажмите **«Скачать результат»** — это PDF из пайплайна  

Типичное время на один документ: **от ~20 секунд до нескольких минут** (зависит от GigaChat и размера файла).

---

## Как это работает (коротко)

1. **Gateway** принимает файл, кладёт в MinIO (`source-documents`), публикует событие в RabbitMQ.  
2. **document-service** парсит техпаспорт → JSON (факты + `source_narrative` + `source_tables`).  
3. **ai-service** генерирует тексты разделов через **GigaChat** (контекст — разобранный паспорт).  
4. Таблицы из техпаспорта вставляются в JSON инструкции как реальные гриды.  
5. **assembler-service** собирает DOCX по ГОСТ-шаблону региона `chita` и конвертирует в PDF через LibreOffice.  
6. PDF лежит в MinIO (`result-documents`); скачивание: `GET /api/v1/tasks/{id}/download`.

> Векторная база (Qdrant + референсные инструкции) в коде задумана (`ai_engine.py`, `ingest_data.py`), но **в текущем docker-compose по умолчанию не поднята**. Рабочий путь — GigaChat по JSON техпаспорта + ГОСТ-сборка assembler.

---

## Структура monorepo

| Каталог | Роль | Стек |
|---------|------|------|
| `gateway/` | API, JWT, задачи, MinIO, RabbitMQ, PostgreSQL | Java 21, Spring Boot |
| `frontend/` | UI загрузки и скачивания | React 19, Vite, nginx в Docker |
| `document-service/` | Парсинг DOC/DOCX/PDF → JSON | Python, LibreOffice |
| `ai-service/` | Генерация разделов (GigaChat) | Python, langchain-gigachat |
| `assembler-service/` | JSON → DOCX → PDF | Python, python-docx, LibreOffice |

Рабочая интеграционная ветка разработки: `integration`. Стабильная точка для запуска: `main`.

---

## Полезные команды

```bash
# Логи конкретного сервиса
docker logs -f railway-ai-service
docker logs -f railway-document-service
docker logs -f railway-assembler-service
docker logs -f railway-gateway

# Пересобрать только AI после смены ключа/кода
docker compose --env-file .env up -d --build ai-service

# Полный перезапуск «с нуля» (данные БД/MinIO сохранятся в volumes)
docker compose --env-file .env down
docker compose --env-file .env up -d --build

# Удалить и volumes (осторожно: сотрёт задачи и файлы)
docker compose down -v
```

---

## Frontend локально (опционально)

Если удобнее Vite с hot-reload:

```bash
# Инфраструктура и бэкенд уже через compose
docker compose --env-file .env up -d

cd frontend
npm ci
npx vite --host 127.0.0.1 --port 5173
```

Прокси на Gateway настроен в `frontend/vite.config.js` (`http://localhost:8080`).

---

## API (кратко)

Базовый префикс: `http://localhost:8080/api`

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/auth/register` | Регистрация |
| `POST` | `/v1/auth/login` | Логин → JWT |
| `POST` | `/v1/tasks` | Загрузка файла (`multipart`, поле `file`) |
| `GET` | `/v1/tasks/{id}/status` | Статус |
| `GET` | `/v1/tasks/{id}/download` | Скачать PDF (после `COMPLETED`) |
| `GET` | `/v1/tasks/{id}/content` | Текст инструкции из generated-json |
| `PUT` | `/v1/tasks/{id}/content` | Сохранить правки текста (PDF сам не пересобирается) |

Пример загрузки через curl (после логина):

```bash
curl -X POST "http://localhost:8080/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"YourPassword1!"}'

curl -X POST "http://localhost:8080/api/v1/tasks" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@./passport.doc;type=application/msword"
```

---

## Типичные проблемы

| Симптом | Что проверить |
|---------|----------------|
| Frontend пустой / API 502 | `docker compose ps` — gateway healthy? |
| Задача `FAILED` на парсинге | формат файла; логи `railway-document-service` |
| Заглушки / пустой смысл в PDF | задан ли `GIGACHAT_CREDENTIALS` в `.env`, пересобран ли `ai-service` |
| Таблицы «ломаные» | нужна актуальная `main`/`integration` после фиксов шапок; перезалейте файл |
| Ошибка `original_file_type` | уже исправлено миграцией V3; пересоберите gateway |
| Долгая первая сборка | нормально: Maven + LibreOffice в образах |

---

## Разработка

```bash
git checkout integration   # текущая feature/integration-линия
# ... правки ...
docker compose --env-file .env up -d --build <service>
```

Секреты только в `.env`. Шаблон — `.env.example`.
