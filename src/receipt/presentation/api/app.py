import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from receipt.application.mediator import Mediator
from receipt.presentation.api.errors import install_error_handlers
from receipt.presentation.api.routers import admin, chat, imports, recipes, system
from receipt.presentation.api.schemas import DoneData, ErrorData, SourcesData, TokenData, ToolData
from receipt.presentation.api.security import api_key_guard


def create_app(mediator: Mediator, api_key: str) -> FastAPI:
    """One process (one uvicorn worker): import statuses, chats and the import limit live in it."""
    background_tasks: set[asyncio.Task[object]] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)

    app = FastAPI(
        title="Recipe Bot API",
        description=(
            "Рецепты из видео YouTube, TikTok и Instagram. Все запросы — с заголовком X-API-Key."
        ),
        lifespan=lifespan,
        # Every endpoint, /health and the chat stream included.
        dependencies=[Depends(api_key_guard(api_key))],
    )
    app.state.mediator = mediator
    app.state.background_tasks = background_tasks
    install_error_handlers(app)
    for router in (system.router, imports.router, recipes.router, chat.router, admin.router):
        app.include_router(router)
    _document_stream_events(app)
    return app


def _document_stream_events(app: FastAPI) -> None:
    """The SSE event bodies are not return types, so FastAPI would not list them in OpenAPI;
    the frontend generates its types from there."""
    original = app.openapi

    def openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in (TokenData, ToolData, SourcesData, DoneData, ErrorData):
            components[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
