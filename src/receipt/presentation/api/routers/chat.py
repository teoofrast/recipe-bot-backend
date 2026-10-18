import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from receipt.application.errors import ApplicationError, LlmUnavailableError
from receipt.application.ports.assistant import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    TokenEvent,
    ToolEvent,
)
from receipt.application.recipes.ask import AskQuestion
from receipt.presentation.api.dependencies import MediatorDep
from receipt.presentation.api.schemas import (
    ChatRequest,
    ChatResponse,
    DoneData,
    ErrorData,
    ErrorResponse,
    SourceRecipeResponse,
    SourcesData,
    TokenData,
    ToolData,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# Keeps proxies and browsers from closing the connection while the model is thinking.
PING_SECONDS = 15


def to_data(event: ChatEvent) -> BaseModel:
    match event:
        case TokenEvent(text=text):
            return TokenData(text=text)
        case ToolEvent(name=name, description=description):
            return ToolData(name=name, description=description)
        case SourcesEvent(recipes=recipes):
            return SourcesData(recipes=[SourceRecipeResponse(**vars(recipe)) for recipe in recipes])
        case DoneEvent(model=model):
            return DoneData(model=model)
        case ErrorEvent(message=message):
            return ErrorData(message=message)


_STREAM_DOC: dict[str, Any] = {
    "responses": {
        200: {
            "description": "Поток SSE: `event: token|tool|sources|done|error`, `data:` — JSON",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "oneOf": [
                            {"$ref": f"#/components/schemas/{model.__name__}"}
                            for model in (TokenData, ToolData, SourcesData, DoneData, ErrorData)
                        ]
                    }
                }
            },
        }
    }
}


@router.post("/stream", **_STREAM_DOC, response_class=EventSourceResponse)
async def chat_stream(body: ChatRequest, mediator: MediatorDep) -> EventSourceResponse:
    """Ответ ассистента потоком. Читать через fetch (EventSource не умеет POST и заголовки)."""

    async def events() -> AsyncIterator[dict[str, str]]:
        stream = mediator.stream(AskQuestion(chat_id=body.chat_id, text=body.text))
        try:
            async for event in stream:
                data = to_data(event)
                yield {"event": data.event, "data": data.model_dump_json(exclude={"event"})}  # type: ignore[attr-defined]
        except ApplicationError:
            # Unexpected failures arrive here wrapped by the mediator, already logged.
            error = ErrorData(message="Внутренняя ошибка, попробуйте ещё раз")
            yield {"event": "error", "data": error.model_dump_json(exclude={"event"})}
        finally:
            # The client went away (sse-starlette cancels this generator): stop the assistant.
            await stream.aclose()  # type: ignore[attr-defined]

    return EventSourceResponse(events(), ping=PING_SECONDS, headers={"X-Accel-Buffering": "no"})


@router.post("", responses={503: {"model": ErrorResponse}})
async def chat(body: ChatRequest, mediator: MediatorDep) -> ChatResponse:
    """Ответ ассистента целиком (для Telegram-бота)."""
    text: list[str] = []
    sources: list[SourceRecipeResponse] = []
    model = None
    async for event in mediator.stream(AskQuestion(chat_id=body.chat_id, text=body.text)):
        match event:
            case TokenEvent(text=piece):
                text.append(piece)
            case SourcesEvent(recipes=recipes):
                sources = [SourceRecipeResponse(**vars(recipe)) for recipe in recipes]
            case DoneEvent(model=served_by):
                model = served_by
            case ErrorEvent(message=message):
                raise LlmUnavailableError(message)
    return ChatResponse(text="".join(text).strip(), sources=sources, model=model)
