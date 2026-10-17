import functools
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from receipt.application.cqrs import Request, StreamQuery

type Resolver = Callable[[type[Any]], Any]
type Next[T] = Callable[[], Awaitable[T]]
type StreamNext[T] = Callable[[], AsyncIterator[T]]


class Behavior(Protocol):
    """Wraps every request passing through the mediator: logging, error handling, metrics."""

    async def handle(self, request: Request[Any], call_next: Next[Any]) -> Any: ...

    def handle_stream(
        self, request: StreamQuery[Any], call_next: StreamNext[Any]
    ) -> AsyncIterator[Any]: ...


class Mediator:
    """Routes a request to its handler through the behaviors pipeline.

    ``handlers`` maps a request type to a handler class; the handler instance comes from
    ``resolve`` (the DI container), so its dependencies are injected through the constructor.
    The first behavior in ``behaviors`` is the outermost one.
    """

    def __init__(
        self,
        resolve: Resolver,
        handlers: Mapping[type[Any], type[Any]],
        behaviors: Sequence[Behavior] = (),
    ) -> None:
        self._resolve = resolve
        self._handlers = handlers
        self._behaviors = behaviors

    async def send[TResult](self, request: Request[TResult]) -> TResult:
        handler = self._handler_for(request)
        call: Next[TResult] = functools.partial(handler.handle, request)
        for behavior in reversed(self._behaviors):
            call = functools.partial(behavior.handle, request, call)
        return await call()

    def stream[TChunk](self, request: StreamQuery[TChunk]) -> AsyncIterator[TChunk]:
        handler = self._handler_for(request)
        call: StreamNext[TChunk] = functools.partial(handler.handle, request)
        for behavior in reversed(self._behaviors):
            call = functools.partial(behavior.handle_stream, request, call)
        return call()

    def _handler_for(self, request: object) -> Any:
        handler_type = self._handlers.get(type(request))
        if handler_type is None:
            raise LookupError(f"No handler registered for {type(request).__name__}")
        return self._resolve(handler_type)
