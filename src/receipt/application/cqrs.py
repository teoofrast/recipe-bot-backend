"""CQRS building blocks: requests and the handlers that serve them.

Requests are frozen dataclasses that subclass one of the bases below, parametrized
with what the handler returns, e.g. ``class GetRecipe(Query[Recipe])``.
"""

from collections.abc import AsyncIterator
from typing import Protocol


class Request[TResult]:
    """Anything sent through ``Mediator.send``."""


class Command[TResult](Request[TResult]):
    """Changes state."""


class Query[TResult](Request[TResult]):
    """Reads state, never changes it."""


class StreamQuery[TChunk]:
    """Reads state and answers with a stream of chunks through ``Mediator.stream``."""


class Handler[TRequest, TResult](Protocol):
    async def handle(self, request: TRequest) -> TResult: ...


class StreamHandler[TRequest, TChunk](Protocol):
    def handle(self, request: TRequest) -> AsyncIterator[TChunk]: ...
