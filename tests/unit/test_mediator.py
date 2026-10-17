import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from receipt.application.behaviors import ErrorBehavior, LoggingBehavior
from receipt.application.cqrs import Query, Request, StreamQuery
from receipt.application.errors import UnexpectedError
from receipt.application.mediator import Behavior, Mediator, Next, StreamNext
from receipt.domain.errors import DomainError


@dataclass(frozen=True)
class Echo(Query[str]):
    text: str


class EchoHandler:
    async def handle(self, request: Echo) -> str:
        return request.text


@dataclass(frozen=True)
class Fail(Query[None]):
    error: Exception


class FailHandler:
    async def handle(self, request: Fail) -> None:
        raise request.error


@dataclass(frozen=True)
class Count(StreamQuery[int]):
    up_to: int
    fail_at: int | None = None


class CountHandler:
    async def handle(self, request: Count) -> AsyncIterator[int]:
        for number in range(request.up_to):
            if number == request.fail_at:
                raise RuntimeError("boom")
            yield number


@dataclass(frozen=True)
class Unregistered(Query[None]):
    pass


class RecordingBehavior:
    def __init__(self, name: str, log: list[str]) -> None:
        self._name = name
        self._log = log

    async def handle(self, request: Request[Any], call_next: Next[Any]) -> Any:
        self._log.append(f"{self._name}:before")
        result = await call_next()
        self._log.append(f"{self._name}:after")
        return result

    async def handle_stream(
        self, request: StreamQuery[Any], call_next: StreamNext[Any]
    ) -> AsyncIterator[Any]:
        self._log.append(f"{self._name}:start")
        async for chunk in call_next():
            yield chunk
        self._log.append(f"{self._name}:end")


def make_mediator(*behaviors: Behavior) -> Mediator:
    handlers = {Echo: EchoHandler, Fail: FailHandler, Count: CountHandler}
    return Mediator(lambda handler_type: handler_type(), handlers, behaviors)


async def collect[T](chunks: AsyncIterator[T]) -> list[T]:
    return [chunk async for chunk in chunks]


async def test_send_returns_handler_result() -> None:
    assert await make_mediator().send(Echo("hello")) == "hello"


async def test_stream_yields_handler_chunks() -> None:
    assert await collect(make_mediator().stream(Count(up_to=3))) == [0, 1, 2]


async def test_unregistered_request_raises_lookup_error() -> None:
    with pytest.raises(LookupError, match="Unregistered"):
        await make_mediator().send(Unregistered())


async def test_behaviors_wrap_send_first_is_outermost() -> None:
    log: list[str] = []
    mediator = make_mediator(RecordingBehavior("outer", log), RecordingBehavior("inner", log))

    await mediator.send(Echo("hi"))

    assert log == ["outer:before", "inner:before", "inner:after", "outer:after"]


async def test_behaviors_wrap_stream() -> None:
    log: list[str] = []
    mediator = make_mediator(RecordingBehavior("outer", log), RecordingBehavior("inner", log))

    assert await collect(mediator.stream(Count(up_to=2))) == [0, 1]
    assert log == ["outer:start", "inner:start", "inner:end", "outer:end"]


async def test_error_behavior_lets_domain_errors_through() -> None:
    error = DomainError("recipe has no ingredients")

    with pytest.raises(DomainError) as raised:
        await make_mediator(ErrorBehavior()).send(Fail(error))

    assert raised.value is error


async def test_error_behavior_wraps_unexpected_errors() -> None:
    error = RuntimeError("boom")

    with pytest.raises(UnexpectedError) as raised:
        await make_mediator(ErrorBehavior()).send(Fail(error))

    assert raised.value.__cause__ is error


async def test_error_behavior_wraps_errors_in_the_middle_of_a_stream() -> None:
    received: list[int] = []

    with pytest.raises(UnexpectedError):
        async for chunk in make_mediator(ErrorBehavior()).stream(Count(up_to=5, fail_at=2)):
            received.append(chunk)

    assert received == [0, 1]


async def test_logging_behavior_logs_stream_start_and_end(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="receipt.mediator")

    await collect(make_mediator(LoggingBehavior()).stream(Count(up_to=2)))

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == "Count stream started"
    assert messages[1].startswith("Count stream ended: 2 chunks")
