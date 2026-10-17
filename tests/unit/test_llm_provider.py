import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import Runnable, RunnableConfig

from receipt.application.errors import LlmUnavailableError
from receipt.infrastructure.llm.provider import (
    ChatModelProvider,
    Purpose,
    _ModelLogger,
    translate_llm_errors,
)


class ScriptedModel(Runnable[Any, Any]):
    """Stands in for a chat model: answers ``reply``, or raises ``error`` (before or mid-stream)."""

    def __init__(
        self,
        name: str,
        reply: str = "",
        error: BaseException | None = None,
        delay: float = 0,
        fail_after_chunks: int | None = None,
    ) -> None:
        self.name = name
        self.reply = reply or f"answer from {name}"
        self.error = error
        self.delay = delay
        self.fail_after_chunks = fail_after_chunks
        self.calls = 0

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.reply

    async def astream(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.error is not None and self.fail_after_chunks is None:
            raise self.error
        for number, word in enumerate(self.reply.split()):
            if number == self.fail_after_chunks:
                assert self.error is not None
                raise self.error
            yield word


def status_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return cls("error", response=httpx.Response(status, request=request), body=None)


def provider(*models: ScriptedModel, api_key: str | None = "sk-test", timeout: float = 5):
    by_id = {model.name: model for model in models}
    return ChatModelProvider(
        api_key=api_key,
        models={Purpose.EXTRACT: list(by_id), Purpose.CHAT: []},
        timeout_seconds=timeout,
        model_factory=by_id.__getitem__,  # type: ignore[arg-type]
    )


async def test_first_model_answers() -> None:
    first, second = ScriptedModel("a"), ScriptedModel("b")

    result = await provider(first, second).with_fallbacks(Purpose.EXTRACT).ainvoke("hi")

    assert result == "answer from a"
    assert (first.calls, second.calls) == (1, 0)


@pytest.mark.parametrize(
    "error",
    [
        status_error(openai.RateLimitError, 429),
        status_error(openai.InternalServerError, 502),
        status_error(openai.NotFoundError, 404),
        status_error(openai.BadRequestError, 400),
        status_error(openai.PermissionDeniedError, 403),
        openai.APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai")),
        # What langchain-openai raises when OpenRouter puts an error into a 200 response.
        ValueError({"message": "rate-limited upstream", "code": 429}),
    ],
    ids=["429", "502", "404", "400", "403", "timeout", "error-in-body"],
)
async def test_failing_model_hands_over_to_the_next(error: BaseException) -> None:
    first, second = ScriptedModel("a", error=error), ScriptedModel("b")

    result = await provider(first, second).with_fallbacks(Purpose.EXTRACT).ainvoke("hi")

    assert result == "answer from b"


async def test_build_is_applied_to_every_model() -> None:
    built: list[str] = []

    def build(model: Any) -> Any:
        built.append(model.name)
        return model

    provider(ScriptedModel("a"), ScriptedModel("b")).with_fallbacks(Purpose.EXTRACT, build)

    assert built == ["a", "b"]


async def test_stuck_model_is_cut_off_by_the_deadline() -> None:
    slow, fast = ScriptedModel("slow", delay=5), ScriptedModel("fast")

    chain = provider(slow, fast, timeout=0.05).with_fallbacks(Purpose.EXTRACT)

    assert await chain.ainvoke("hi") == "answer from fast"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (status_error(openai.AuthenticationError, 401), "OPENROUTER_API_KEY"),
        (status_error(openai.APIStatusError, 402), "нет кредитов"),
    ],
)
async def test_key_and_balance_problems_do_not_fall_back(
    error: BaseException, message: str
) -> None:
    first, second = ScriptedModel("a", error=error), ScriptedModel("b")
    chain = provider(first, second).with_fallbacks(Purpose.EXTRACT)

    with pytest.raises(LlmUnavailableError, match=message), translate_llm_errors():
        await chain.ainvoke("hi")

    assert second.calls == 0


async def test_all_models_failing_becomes_llm_unavailable() -> None:
    chain = provider(
        ScriptedModel("a", error=status_error(openai.RateLimitError, 429)),
        ScriptedModel("b", error=status_error(openai.InternalServerError, 503)),
    ).with_fallbacks(Purpose.EXTRACT)

    with pytest.raises(LlmUnavailableError, match="RateLimitError"), translate_llm_errors():
        await chain.ainvoke("hi")


def test_without_key_or_models_nothing_is_built() -> None:
    with pytest.raises(LlmUnavailableError, match="OPENROUTER_API_KEY"):
        provider(ScriptedModel("a"), api_key=None).with_fallbacks(Purpose.EXTRACT)
    with pytest.raises(LlmUnavailableError, match="chat"):
        provider(ScriptedModel("a")).with_fallbacks(Purpose.CHAT)


async def test_stream_falls_back_before_the_first_chunk() -> None:
    first = ScriptedModel("a", error=status_error(openai.RateLimitError, 429))
    second = ScriptedModel("b", reply="берём свёклу")

    chunks = [
        chunk
        async for chunk in provider(first, second).with_fallbacks(Purpose.EXTRACT).astream("hi")
    ]

    assert chunks == ["берём", "свёклу"]


async def test_stream_failing_after_the_first_chunk_is_an_error_not_a_fallback() -> None:
    first = ScriptedModel(
        "a",
        reply="берём свёклу и капусту",
        error=status_error(openai.InternalServerError, 502),
        fail_after_chunks=2,
    )
    second = ScriptedModel("b")
    received: list[str] = []

    with pytest.raises(LlmUnavailableError), translate_llm_errors():
        async for chunk in provider(first, second).with_fallbacks(Purpose.EXTRACT).astream("hi"):
            received.append(chunk)

    assert received == ["берём", "свёклу"]
    assert second.calls == 0


async def test_stream_stuck_before_the_first_chunk_is_cut_off() -> None:
    slow, fast = ScriptedModel("slow", delay=5), ScriptedModel("fast", reply="готово")

    chain = provider(slow, fast, timeout=0.05).with_fallbacks(Purpose.EXTRACT)

    assert [chunk async for chunk in chain.astream("hi")] == ["готово"]


def test_logger_shows_which_model_answered_and_which_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="receipt.infrastructure.llm.provider")
    message = AIMessage(content="ok", response_metadata={"model_name": "nvidia/nemotron-3-super"})
    result = LLMResult(generations=[[ChatGeneration(message=message)]])

    _ModelLogger("nvidia/nemotron:free").on_llm_end(result, run_id=uuid4())
    _ModelLogger("google/gemma:free").on_llm_error(TimeoutError("slow"), run_id=uuid4())

    assert caplog.messages == [
        "LLM nvidia/nemotron:free answered (served by nvidia/nemotron-3-super)",
        "LLM google/gemma:free failed: TimeoutError: slow",
    ]


def test_logger_shows_a_streamed_model_name_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="receipt.infrastructure.llm.provider")
    message = AIMessage(
        content="ok", response_metadata={"model_name": "vendor/m:freevendor/m:free"}
    )

    _ModelLogger("vendor/m:free").on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=uuid4()
    )

    assert caplog.messages == ["LLM vendor/m:free answered (served by vendor/m:free)"]
