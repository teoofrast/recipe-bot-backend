from httpx import AsyncClient

from receipt.application.errors import UnexpectedError
from receipt.application.ports.assistant import (
    DoneEvent,
    ErrorEvent,
    SourceRecipe,
    SourcesEvent,
    TokenEvent,
    ToolEvent,
)
from tests.api.test_system import parse_sse
from tests.fakes import FakeAssistant

QUESTION = {"chat_id": "web-1", "text": "Что приготовить из курицы?"}
ANSWER = [
    ToolEvent("search_recipes", "Ищу рецепты: «курица»"),
    TokenEvent("Курица "),
    TokenEvent("карри."),
    SourcesEvent((SourceRecipe("a1", "Курица карри", "https://youtu.be/c1"),)),
    DoneEvent(model="nvidia/nemotron:free"),
]


async def test_chat_stream_sends_each_event(client: AsyncClient, assistant: FakeAssistant) -> None:
    assistant.events = ANSWER

    response = await client.post("/chat/stream", json=QUESTION)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert parse_sse(response.text) == [
        ("tool", {"name": "search_recipes", "description": "Ищу рецепты: «курица»"}),
        ("token", {"text": "Курица "}),
        ("token", {"text": "карри."}),
        (
            "sources",
            {
                "recipes": [
                    {"recipe_id": "a1", "title": "Курица карри", "url": "https://youtu.be/c1"}
                ]
            },
        ),
        ("done", {"model": "nvidia/nemotron:free"}),
    ]
    assert assistant.questions == [("web-1", "Что приготовить из курицы?")]


async def test_a_failure_in_the_middle_ends_with_an_error_event(
    client: AsyncClient, assistant: FakeAssistant
) -> None:
    assistant.events = [TokenEvent("Курица ")]
    assistant.error = KeyError("bug")  # wrapped by the mediator as an unexpected error

    events = parse_sse((await client.post("/chat/stream", json=QUESTION)).text)

    assert events == [
        ("token", {"text": "Курица "}),
        ("error", {"message": "Внутренняя ошибка, попробуйте ещё раз"}),
    ]


async def test_chat_returns_the_whole_answer(client: AsyncClient, assistant: FakeAssistant) -> None:
    assistant.events = ANSWER

    response = await client.post("/chat", json=QUESTION)

    assert response.json() == {
        "text": "Курица карри.",
        "sources": [{"recipe_id": "a1", "title": "Курица карри", "url": "https://youtu.be/c1"}],
        "model": "nvidia/nemotron:free",
    }


async def test_chat_reports_an_unavailable_assistant(
    client: AsyncClient, assistant: FakeAssistant
) -> None:
    assistant.events = [ErrorEvent("Ни одна языковая модель не ответила")]

    response = await client.post("/chat", json=QUESTION)

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "llm_unavailable", "message": "Ни одна языковая модель не ответила"}
    }


async def test_chat_validates_the_question(client: AsyncClient) -> None:
    response = await client.post("/chat", json={"chat_id": "", "text": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unexpected_errors_never_show_their_details() -> None:
    from receipt.presentation.api.errors import status_for

    assert status_for(UnexpectedError("KeyError: secret path")) == (500, "internal_error")
