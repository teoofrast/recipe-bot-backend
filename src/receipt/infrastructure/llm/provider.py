"""Language models through OpenRouter, each task with its own list of models to fall back on."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from typing import Any
from uuid import UUID

import openai
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from receipt.application.errors import LlmUnavailableError

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"

# Another model may well succeed after these. Wrong key (401) and empty balance (402) are
# not here: every model would fail the same way.
FALLBACK_ERRORS: tuple[type[BaseException], ...] = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,  # 429: free models have tight limits
    openai.InternalServerError,  # 5xx, provider down
    openai.NotFoundError,  # model removed or no provider supports the request (tools, JSON)
    openai.BadRequestError,  # a provider rejected a parameter this model does not support
    openai.PermissionDeniedError,  # 403: the provider's moderation flagged the input
    openai.UnprocessableEntityError,
    OutputParserException,  # invalid JSON instead of the requested structure
    # JSON not matching the schema (pydantic's ValidationError is a ValueError), and errors
    # OpenRouter puts into a 200 response body, which langchain-openai raises as ValueError:
    # "{'message': '... is temporarily rate-limited upstream', 'code': 429}".
    ValueError,
    TimeoutError,  # the per-model deadline, see _Deadline
)


class Purpose(StrEnum):
    EXTRACT = "extract"  # needs structured output (JSON by schema)
    CHAT = "chat"  # needs tool calling and streaming


class _ModelLogger(BaseCallbackHandler):
    """Logs which model answered and which failed, so fallbacks are visible in the logs."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        served_by = (response.llm_output or {}).get("model_name")
        if not served_by and response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
            served_by = getattr(message, "response_metadata", {}).get("model_name")
        logger.info("LLM %s answered (served by %s)", self._model_id, _once(served_by) or "?")

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        logger.warning("LLM %s failed: %s: %s", self._model_id, type(error).__name__, error)


def _once(text: str | None) -> str | None:
    """ "ab" from "abab": streamed chunks' metadata is concatenated, so the name repeats."""
    if not text:
        return text
    for period in range(1, len(text) // 2 + 1):
        if len(text) % period == 0 and text[:period] * (len(text) // period) == text:
            return text[:period]
    return text


class _Deadline(Runnable[Any, Any]):
    """A hard limit on one model's call.

    OpenRouter keeps the connection alive while a model is thinking, so the HTTP read timeout
    never fires: slow free models were seen answering after 2-3 minutes. For streaming, the
    limit is on the first chunk, the moment after which fallbacks are no longer possible.
    """

    def __init__(self, inner: Runnable[Any, Any], seconds: float) -> None:
        self.inner = inner
        self.seconds = seconds

    def invoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        return self.inner.invoke(input, config, **kwargs)

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None, **kwargs: Any) -> Any:
        async with asyncio.timeout(self.seconds):
            return await self.inner.ainvoke(input, config, **kwargs)

    async def astream(
        self, input: Any, config: RunnableConfig | None = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        stream = self.inner.astream(input, config, **kwargs)
        try:
            async with asyncio.timeout(self.seconds):
                first = await anext(stream)
        except BaseException:
            await stream.aclose()
            raise
        yield first
        async for chunk in stream:
            yield chunk


class ChatModelProvider:
    """Builds OpenRouter chat models and chains them with fallbacks.

    Each model gets a hard deadline and one retry, so a dead or stuck model hands over to
    the next one in seconds rather than after minutes.
    """

    def __init__(
        self,
        api_key: str | None,
        models: Mapping[Purpose, Sequence[str]],
        *,
        base_url: str = OPENROUTER_URL,
        timeout_seconds: float | Mapping[Purpose, float] = 30,
        max_retries: int = 1,
        model_factory: Callable[[str, float], BaseChatModel] | None = None,
    ) -> None:
        self._api_key = api_key
        self._models = {purpose: list(ids) for purpose, ids in models.items()}
        self._base_url = base_url
        self._timeouts = (
            dict(timeout_seconds)
            if isinstance(timeout_seconds, Mapping)
            else dict.fromkeys(Purpose, timeout_seconds)
        )
        self._max_retries = max_retries
        self._model_factory = model_factory or self._openrouter_model

    def model_ids(self, purpose: Purpose) -> list[str]:
        return list(self._models.get(purpose, []))

    def with_fallbacks(
        self,
        purpose: Purpose,
        build: Callable[[BaseChatModel], Runnable[Any, Any]] = lambda model: model,
    ) -> Runnable[Any, Any]:
        """A runnable that tries the purpose's models in order.

        ``build`` turns each model into the actual step, e.g.
        ``lambda model: model.with_structured_output(Recipe)``, so that an invalid answer of
        one model also moves on to the next. Call it inside ``translate_llm_errors()``.
        """
        if not self._api_key:
            raise LlmUnavailableError("Не задан OPENROUTER_API_KEY")
        model_ids = self.model_ids(purpose)
        if not model_ids:
            raise LlmUnavailableError(f"Не задан список моделей для задачи «{purpose}»")
        timeout = self._timeouts[purpose]
        first, *rest = [
            _Deadline(build(self._model_factory(model_id, timeout)), timeout)
            for model_id in model_ids
        ]
        if not rest:
            return first
        return first.with_fallbacks(rest, exceptions_to_handle=FALLBACK_ERRORS)

    def _openrouter_model(self, model_id: str, timeout: float) -> BaseChatModel:
        assert self._api_key is not None
        return ChatOpenAI(
            model=model_id,
            api_key=SecretStr(self._api_key),
            base_url=self._base_url,
            timeout=timeout,
            max_retries=self._max_retries,
            default_headers={"X-Title": "Recipe Bot"},
            callbacks=[_ModelLogger(model_id)],
        )


@contextmanager
def translate_llm_errors() -> Iterator[None]:
    """Turns what is left after all fallbacks into LlmUnavailableError with a clear reason."""
    try:
        yield
    except openai.AuthenticationError as error:
        raise LlmUnavailableError(
            "OpenRouter не принял ключ: проверьте OPENROUTER_API_KEY"
        ) from error
    except openai.APIStatusError as error:
        if error.status_code == 402:
            raise LlmUnavailableError("На балансе OpenRouter нет кредитов") from error
        if isinstance(error, FALLBACK_ERRORS):
            raise _all_failed(error) from error
        raise
    except FALLBACK_ERRORS as error:
        raise _all_failed(error) from error


def _all_failed(error: BaseException) -> LlmUnavailableError:
    return LlmUnavailableError(
        f"Ни одна языковая модель не ответила (первая ошибка: {type(error).__name__})"
    )
