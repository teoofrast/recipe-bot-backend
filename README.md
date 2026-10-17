# recipe-bot-backend

Бэкенд чат-бота по рецептам: парсит рецепты из видео YouTube / TikTok / Instagram и отвечает на вопросы по ним.

**Стек:** Python 3.12, FastAPI, LangGraph, OpenRouter, Chroma, punq, aiogram.
**Архитектура:** чистая архитектура + CQRS + медиатор.

Фронтенд: [recipe-bot-frontend](https://github.com/teoofrast/recipe-bot-frontend)

## Запуск в Docker

Оба репозитория должны лежать рядом:

```
receipt/
├── recipe-bot-backend/
└── recipe-bot-frontend/
```

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (Swagger: http://localhost:8000/docs)
- Веб-чат: http://localhost:3000
- Telegram-бот (с карточки 10): `docker compose --profile bot up`

Если фронтенд лежит в другом месте — укажите путь в `FRONTEND_PATH` в `.env`.

## Тесты и проверки

```bash
docker compose run --rm api pytest
```

Локально без Docker (нужен [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pre-commit install   # ruff перед каждым коммитом
```

## Структура

```
src/receipt/
├── domain/          # сущности и правила, без внешних зависимостей
├── application/     # порты, команды/запросы и их обработчики
├── infrastructure/  # адаптеры: yt-dlp, Whisper, OpenRouter, Chroma, LangGraph
├── presentation/    # api (FastAPI), bot (Telegram), cli
└── bootstrap/       # сборка зависимостей (punq)
```
