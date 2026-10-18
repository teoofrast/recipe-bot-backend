"""The recipe assistant: a LangGraph agent (model <-> tools) with per-chat memory."""

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from receipt.application.errors import ApplicationError
from receipt.application.mediator import Mediator
from receipt.application.ports.assistant import (
    ChatEvent,
    DoneEvent,
    SourceRecipe,
    SourcesEvent,
    TokenEvent,
    ToolEvent,
)
from receipt.infrastructure.assistant.tools import describe_tool_call, make_tools
from receipt.infrastructure.llm.provider import (
    ChatModelProvider,
    Purpose,
    once,
    translate_llm_errors,
)

SYSTEM_PROMPT = """Ты — помощник по личной коллекции рецептов. Рецепты пользователь сохранил \
сам из видео YouTube, TikTok и Instagram.

Правила:
1. Отвечай только по сохранённым рецептам. Что есть в коллекции — узнавай через search_recipes \
или list_recipes, не по памяти.
2. Поиск всегда возвращает ближайшие по смыслу рецепты, даже если подходящих нет. Сам проверь, \
подходят ли они к вопросу. Если подходящего нет — прямо скажи, что в коллекции такого рецепта \
нет, и не выдавай похожий за нужный.
3. Прежде чем отвечать про конкретный рецепт (состав, количества, шаги, пересчёт) — открой его \
через get_recipe. Пересказывай рецепт как есть: не добавляй шаги, количества, время и порции, \
которых в нём нет. Если шагов в рецепте нет — так и скажи.
4. Пересчёт порций: умножай количества пропорционально. Если исходное число порций не указано, \
скажи об этом и считай от исходного рецепта целиком.
5. Замены ингредиентов и советы можно давать из общих кулинарных знаний, но явно помечай, что \
этого нет в рецепте.
6. Отвечай по-русски, коротко и по делу; списки — для ингредиентов и шагов. Называй рецепт, \
на который опираешься."""

# Model calls plus tool calls in one answer; a model stuck in a tool loop stops here.
RECURSION_LIMIT = 12


class AssistantGaveUpError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Не получилось ответить: слишком много шагов. Переформулируйте вопрос")


class LangGraphRecipeAssistant:
    def __init__(
        self, mediator: Mediator, provider: ChatModelProvider, history_messages: int = 20
    ) -> None:
        self._provider = provider
        self._history = history_messages
        self._tools = make_tools(mediator)
        self._graph = self._build()

    async def stream(self, chat_id: str, text: str) -> AsyncIterator[ChatEvent]:
        config: Any = {"configurable": {"thread_id": chat_id}, "recursion_limit": RECURSION_LIMIT}
        sources: dict[str, SourceRecipe] = {}
        model: str | None = None
        try:
            async for mode, payload in self._graph.astream(
                {"messages": [HumanMessage(text)]}, config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    # Token chunks of a streaming model, or the whole message of a model that
                    # does not stream (AIMessageChunk is an AIMessage too).
                    if (
                        metadata.get("langgraph_node") == "agent"
                        and isinstance(chunk, AIMessage)
                        and isinstance(chunk.content, str)
                        and chunk.content
                    ):
                        yield TokenEvent(chunk.content)
                    continue
                for update in payload.values():
                    for message in (update or {}).get("messages", []):
                        if isinstance(message, AIMessage):
                            # Streamed chunks' metadata is concatenated: "m" arrives as "mm".
                            model = once(message.response_metadata.get("model_name")) or model
                            for call in message.tool_calls:
                                yield ToolEvent(
                                    call["name"], describe_tool_call(call["name"], call["args"])
                                )
                        elif isinstance(message, ToolMessage) and message.artifact:
                            for source in message.artifact:
                                sources[source.recipe_id] = source
        except GraphRecursionError as error:
            raise AssistantGaveUpError() from error
        if sources:
            yield SourcesEvent(tuple(sources.values()))
        yield DoneEvent(model=model)

    def _build(self) -> Any:
        graph = StateGraph(MessagesState)
        graph.add_node("agent", self._agent)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")
        return graph.compile(checkpointer=InMemorySaver())

    async def _agent(self, state: MessagesState) -> dict[str, list[Any]]:
        # Only the recent part of a long chat goes to the model: free models have small limits.
        history = trim_messages(
            state["messages"],
            strategy="last",
            token_counter=len,
            max_tokens=self._history,
            start_on="human",
        )
        chain = self._provider.with_fallbacks(
            Purpose.CHAT, lambda model: model.bind_tools(self._tools)
        )
        with translate_llm_errors():
            response = await chain.ainvoke([SystemMessage(SYSTEM_PROMPT), *history])
        return {"messages": [response]}
