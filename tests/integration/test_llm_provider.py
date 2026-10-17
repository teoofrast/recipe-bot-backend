"""Real free models on OpenRouter, with a model that does not exist put first in each list.

Run explicitly: ``uv run pytest -m integration -k llm``. Free models hit shared rate limits
now and then; the fallbacks are exactly what is being tested here.
"""

import logging

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from pydantic import BaseModel

from receipt.bootstrap.settings import Settings
from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose, translate_llm_errors

SETTINGS = Settings()
API_KEY = SETTINGS.openrouter_api_key.get_secret_value() if SETTINGS.openrouter_api_key else None
MISSING_MODEL = "nonexistent-vendor/model-that-does-not-exist:free"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(API_KEY is None, reason="OPENROUTER_API_KEY is not set"),
]

RECIPE_TEXT = (
    "Сырники: творог 400 г отжимаю через марлю, добавляю 1 яйцо, 2 ст. л. сметаны, "
    "сахар 2 ст. л. и муку 3 ст. л. Формирую сырники, жарю по 2 минуты с каждой стороны."
)


class Ingredient(BaseModel):
    name: str
    quantity: float | None
    unit: str | None


class Recipe(BaseModel):
    title: str
    ingredients: list[Ingredient]


@tool
def search_recipes(query: str) -> str:
    """Search saved recipes by text."""
    return ""


@pytest.fixture
def provider() -> ChatModelProvider:
    return ChatModelProvider(
        api_key=API_KEY,
        models={
            Purpose.EXTRACT: [MISSING_MODEL, *SETTINGS.llm_extract_models],
            Purpose.CHAT: [MISSING_MODEL, *SETTINGS.llm_chat_models],
        },
        timeout_seconds=SETTINGS.llm_timeout_seconds,
    )


@pytest.fixture(autouse=True)
def show_model_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="receipt.infrastructure.llm.provider")
    return caplog


def log_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    messages = [record.getMessage() for record in caplog.records]
    print("\n" + "\n".join(messages))
    return messages


async def test_extraction_falls_back_past_a_missing_model(
    provider: ChatModelProvider, caplog: pytest.LogCaptureFixture
) -> None:
    chain = provider.with_fallbacks(
        Purpose.EXTRACT, lambda model: model.with_structured_output(Recipe, method="json_schema")
    )

    with translate_llm_errors():
        recipe = await chain.ainvoke(
            [("system", "Извлеки рецепт из текста."), ("user", RECIPE_TEXT)]
        )

    # Only that a valid structure came back: how complete it is depends on the prompt and
    # the schema (card 5), and free models vary from call to call.
    assert recipe.ingredients
    assert any("творог" in item.name.lower() for item in recipe.ingredients)
    messages = log_messages(caplog)
    assert any(MISSING_MODEL in message and "failed" in message for message in messages)
    assert any("answered" in message for message in messages)


async def test_chat_tool_call_falls_back_past_a_missing_model(provider: ChatModelProvider) -> None:
    chain = provider.with_fallbacks(Purpose.CHAT, lambda model: model.bind_tools([search_recipes]))

    with translate_llm_errors():
        answer = await chain.ainvoke(
            [
                ("system", "Для поиска рецептов всегда используй инструмент search_recipes."),
                ("user", "Найди мои рецепты с творогом"),
            ]
        )

    assert [call["name"] for call in answer.tool_calls] == ["search_recipes"]


async def test_chat_stream_falls_back_past_a_missing_model(provider: ChatModelProvider) -> None:
    chain = provider.with_fallbacks(Purpose.CHAT)

    with translate_llm_errors():
        chunks = [
            chunk async for chunk in chain.astream([("user", "Скажи «готово» одним словом.")])
        ]

    assert all(isinstance(chunk, AIMessageChunk) for chunk in chunks)
    assert "готово" in "".join(str(chunk.content) for chunk in chunks).lower()
