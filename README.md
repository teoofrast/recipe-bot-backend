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
uv run lint-imports         # границы слоёв
uv run pre-commit install   # ruff + import-linter перед каждым коммитом
```

## CLI

```bash
docker compose run --rm api receipt ping
docker compose run --rm api receipt ping-stream --count 3
```

## Архитектура

```
src/receipt/
├── domain/          # сущности и правила, без внешних зависимостей
├── application/     # порты, команды/запросы и их обработчики, медиатор
├── infrastructure/  # адаптеры: yt-dlp, Whisper, OpenRouter, Chroma, LangGraph
├── presentation/    # api (FastAPI), bot (Telegram), cli
└── bootstrap/       # composition root: контейнер punq, настройки, точки входа
```

Зависимости направлены внутрь: `bootstrap → presentation | infrastructure → application → domain`.
`presentation` и `infrastructure` друг о друге не знают и встречаются только в `bootstrap`.
`domain` и `application` не импортируют фреймворки. Всё это проверяет `lint-imports`.

**Как проходит запрос.** Presentation создаёт команду или запрос и отдаёт медиатору:

```python
# Command / Query -> результат
pong = await mediator.send(Ping())

# StreamQuery -> поток чанков
async for chunk in mediator.stream(PingStream(count=3)):
    ...
```

Медиатор находит обработчик по типу запроса (`HANDLERS` в `bootstrap/container.py`), берёт его из punq
вместе с зависимостями и пропускает вызов через behaviors: `LoggingBehavior` (время, начало и конец потока)
и `ErrorBehavior` (`DomainError` и `ApplicationError` пропускает, остальное логирует и оборачивает в `UnexpectedError`).

**Как добавить use case:**

1. Запрос и обработчик в `application/` — frozen dataclass от `Command[T]`, `Query[T]` или `StreamQuery[T]`.
2. Нужен внешний сервис — порт (`Protocol`) в `application/ports/`, адаптер в `infrastructure/`.
3. Регистрация в `bootstrap/container.py`: запрос → обработчик в `HANDLERS`, порт → адаптер.
4. Эндпоинт или команда CLI в `presentation/`, которые зовут `mediator.send` / `mediator.stream`.

**Тесты** берут ту же сборку контейнера и перерегистрируют внешние адаптеры фейками (`tests/conftest.py`):
в punq побеждает последняя регистрация.
