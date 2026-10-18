"""The real LangGraph assistant and its tools, with a scripted chat model and fake storage."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

from receipt.application.errors import SearchUnavailableError
from receipt.application.mediator import Mediator
from receipt.application.ports.assistant import (
    ChatEvent,
    DoneEvent,
    ErrorEvent,
    SourceRecipe,
    SourcesEvent,
    TokenEvent,
    ToolEvent,
)
from receipt.application.recipes.ask import AskQuestion, AskQuestionHandler
from receipt.application.recipes.collection import SaveRecipe
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.infrastructure.assistant.langgraph_assistant import (
    SYSTEM_PROMPT,
    LangGraphRecipeAssistant,
)
from receipt.infrastructure.assistant.tools import describe_tool_call, make_tools, recipe_text
from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose
from receipt.presentation.cli.app import print_answer
from tests.fakes import FakeRecipeIndex

CURRY = Recipe(
    title="Курица карри",
    ingredients=(Ingredient("куриное филе", 500, "г"), Ingredient("рис")),
    steps=("Обжарьте курицу", "Тушите 20 минут"),
    source=RecipeSource(url="https://youtu.be/c1", platform=Platform.YOUTUBE, video_id="c1"),
    servings=2,
)


class ScriptedChatModel(BaseChatModel):
    """Answers with the next scripted message; the last one repeats. Records what it got."""

    script: list[Any]
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        self.received.append(list(messages))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        # A fresh copy each time: LangGraph replaces, not appends, a message with a known id.
        return ChatResult(generations=[ChatGeneration(message=step.model_copy())])


def tool_call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{name}"}])


def make_assistant(
    mediator: Mediator, script: list[Any], history: int = 20
) -> tuple[LangGraphRecipeAssistant, ScriptedChatModel]:
    model = ScriptedChatModel(script=script)
    provider = ChatModelProvider(
        api_key="sk-test",
        models={Purpose.CHAT: ["scripted"]},
        model_factory=lambda model_id, timeout: model,  # type: ignore[arg-type,return-value]
    )
    return LangGraphRecipeAssistant(mediator, provider, history_messages=history), model


async def collect(bot: LangGraphRecipeAssistant, text: str, chat_id: str = "c") -> list[ChatEvent]:
    return [event async for event in bot.stream(chat_id, text)]


async def ask(bot: LangGraphRecipeAssistant, text: str) -> list[ChatEvent]:
    return [event async for event in AskQuestionHandler(bot).handle(AskQuestion("c", text))]


async def save_curry(mediator: Mediator) -> str:
    result = await mediator.send(SaveRecipe(recipe=CURRY, source_text=SourceText("", "")))
    return result.saved.id


async def test_search_open_and_answer_with_sources(mediator: Mediator) -> None:
    recipe_id = await save_curry(mediator)
    bot, model = make_assistant(
        mediator,
        [
            tool_call("search_recipes", query="курица"),
            tool_call("get_recipe", recipe_id=recipe_id),
            AIMessage(content="Приготовьте курицу карри: 500 г филе."),
        ],
    )

    events = await collect(bot, "Что приготовить из курицы?")

    assert events == [
        ToolEvent("search_recipes", "Ищу рецепты: «курица»"),
        ToolEvent("get_recipe", "Открываю рецепт"),
        TokenEvent("Приготовьте курицу карри: 500 г филе."),
        SourcesEvent((SourceRecipe(recipe_id, "Курица карри", "https://youtu.be/c1"),)),
        DoneEvent(model=None),
    ]
    first_call = model.received[0]
    assert isinstance(first_call[0], SystemMessage)
    assert first_call[0].content == SYSTEM_PROMPT
    # The tool results reached the model.
    tool_texts = " ".join(str(m.content) for m in model.received[2] if m.type == "tool")
    assert f"id={recipe_id}" in tool_texts
    assert "500 г" in tool_texts


async def test_search_results_are_not_sources_until_a_recipe_is_opened(
    mediator: Mediator,
) -> None:
    await save_curry(mediator)
    bot, _ = make_assistant(
        mediator,
        [tool_call("search_recipes", query="пицца"), AIMessage(content="Пиццы в коллекции нет.")],
    )

    events = await collect(bot, "Есть рецепт пиццы?")

    assert not any(isinstance(event, SourcesEvent) for event in events)
    assert TokenEvent("Пиццы в коллекции нет.") in events


async def test_the_conversation_is_remembered_per_chat(mediator: Mediator) -> None:
    bot, model = make_assistant(
        mediator,
        [AIMessage(content="Ответ 1"), AIMessage(content="Ответ 2"), AIMessage(content="Ответ 3")],
    )

    await collect(bot, "Первый вопрос", chat_id="a")
    await collect(bot, "А на 4 порции?", chat_id="a")
    await collect(bot, "Другой чат", chat_id="b")

    second, third = model.received[1], model.received[2]
    assert [m.content for m in second[1:]] == ["Первый вопрос", "Ответ 1", "А на 4 порции?"]
    assert [m.content for m in third[1:]] == ["Другой чат"]


async def test_only_recent_history_goes_to_the_model(mediator: Mediator) -> None:
    bot, model = make_assistant(mediator, [AIMessage(content="ok")], history=3)

    for number in range(4):
        await collect(bot, f"вопрос {number}")

    last = model.received[-1]
    assert isinstance(last[0], SystemMessage)
    assert isinstance(last[1], HumanMessage)  # trimmed so that it starts on a question
    assert len(last) - 1 <= 3
    assert last[-1].content == "вопрос 3"


async def test_llm_failure_becomes_an_error_event(mediator: Mediator) -> None:
    request = httpx.Request("POST", "https://openrouter.ai")
    error = openai.RateLimitError("limit", response=httpx.Response(429, request=request), body=None)
    bot, _ = make_assistant(mediator, [error])

    events = await ask(bot, "Привет")

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "Ни одна языковая модель не ответила" in events[0].message


async def test_a_tool_loop_is_stopped(mediator: Mediator) -> None:
    bot, _ = make_assistant(mediator, [tool_call("list_recipes")])  # calls the tool forever

    events = await ask(bot, "Что есть?")

    assert isinstance(events[-1], ErrorEvent)
    assert "слишком много шагов" in events[-1].message


async def test_closing_the_stream_stops_the_agent(mediator: Mediator) -> None:
    bot, model = make_assistant(
        mediator, [tool_call("list_recipes"), AIMessage(content="Вот список")]
    )

    stream = bot.stream("c", "Что есть?")
    first = await anext(stream)
    await stream.aclose()  # the client went away

    assert isinstance(first, ToolEvent)
    assert len(model.received) == 1  # no second model call after the client left


async def test_empty_question(mediator: Mediator) -> None:
    events = [event async for event in mediator.stream(AskQuestion("c", "  "))]

    assert events == [ErrorEvent("Пустой вопрос")]


# Tools on their own


def tools_by_name(mediator: Mediator) -> dict[str, BaseTool]:
    return {tool.name: tool for tool in make_tools(mediator)}


async def test_tools_answer_in_text(mediator: Mediator) -> None:
    recipe_id = await save_curry(mediator)
    tools = tools_by_name(mediator)

    found = await tools["search_recipes"].ainvoke({"query": "курица"})
    assert f"id={recipe_id} | Курица карри" in found
    assert "Всего рецептов: 1" in await tools["list_recipes"].ainvoke({})
    assert "не найден" in await tools["get_recipe"].ainvoke({"recipe_id": "ffff"})
    assert "Ничего похожего" in await tools["search_recipes"].ainvoke({"query": "пицца"})


async def test_search_tool_reports_an_unavailable_search(
    mediator: Mediator, recipe_index: FakeRecipeIndex
) -> None:
    recipe_index.error = SearchUnavailableError("Chroma недоступна")

    answer = await tools_by_name(mediator)["search_recipes"].ainvoke({"query": "курица"})

    assert answer.startswith("Поиск сейчас недоступен")


def test_recipe_text_and_tool_descriptions() -> None:
    text = recipe_text("a1", CURRY)

    assert text.splitlines()[:4] == [
        "Рецепт a1: Курица карри",
        "порций: 2, время: не указано",
        "Ингредиенты:",
        "- куриное филе: 500 г",
    ]
    assert "1. Обжарьте курицу" in text
    assert describe_tool_call("search_recipes", {"query": "суп"}) == "Ищу рецепты: «суп»"
    assert describe_tool_call("list_recipes", {}) == "Смотрю список рецептов"


async def test_cli_prints_the_streamed_answer(
    mediator: Mediator, capsys: pytest.CaptureFixture[str]
) -> None:
    recipe_id = await save_curry(mediator)
    bot, _ = make_assistant(
        mediator, [tool_call("get_recipe", recipe_id=recipe_id), AIMessage(content="Карри готово.")]
    )

    class AssistantMediator:
        async def stream(self, request: AskQuestion) -> AsyncIterator[ChatEvent]:
            async for event in AskQuestionHandler(bot).handle(request):
                yield event

    await print_answer(AssistantMediator(), "c", "Как приготовить карри?")  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert "… Открываю рецепт" in out
    assert "Карри готово." in out
    assert f"• Курица карри ({recipe_id}) — https://youtu.be/c1" in out


async def test_done_names_the_model_once(mediator: Mediator) -> None:
    answer = AIMessage(
        content="Готово.", response_metadata={"model_name": "vendor/m:freevendor/m:free"}
    )
    bot, _ = make_assistant(mediator, [answer])

    events = await collect(bot, "Привет")

    assert events[-1] == DoneEvent(model="vendor/m:free")
