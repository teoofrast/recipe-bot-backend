"""Ping: checks that a request goes all the way through the mediator to a handler and a port."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from receipt.application.cqrs import Query, StreamQuery
from receipt.application.ports.clock import Clock


@dataclass(frozen=True)
class Pong:
    message: str
    at: datetime


@dataclass(frozen=True)
class Ping(Query[Pong]):
    pass


class PingHandler:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def handle(self, request: Ping) -> Pong:
        return Pong(message="pong", at=self._clock.now())


@dataclass(frozen=True)
class PingStream(StreamQuery[Pong]):
    count: int = 3


class PingStreamHandler:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def handle(self, request: PingStream) -> AsyncIterator[Pong]:
        for number in range(1, request.count + 1):
            yield Pong(message=f"pong {number}", at=self._clock.now())
