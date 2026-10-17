import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from receipt.application.cqrs import Request, StreamQuery
from receipt.application.errors import ApplicationError, UnexpectedError
from receipt.application.mediator import Next, StreamNext
from receipt.domain.errors import DomainError

logger = logging.getLogger("receipt.mediator")

EXPECTED_ERRORS = (DomainError, ApplicationError)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


class LoggingBehavior:
    """Logs every request with its duration; for streams also the start and the chunk count."""

    async def handle(self, request: Request[Any], call_next: Next[Any]) -> Any:
        name = type(request).__name__
        started = time.perf_counter()
        try:
            result = await call_next()
        except Exception:
            logger.info("%s failed in %.1f ms", name, _elapsed_ms(started))
            raise
        logger.info("%s handled in %.1f ms", name, _elapsed_ms(started))
        return result

    async def handle_stream(
        self, request: StreamQuery[Any], call_next: StreamNext[Any]
    ) -> AsyncIterator[Any]:
        name = type(request).__name__
        started = time.perf_counter()
        chunks = 0
        logger.info("%s stream started", name)
        try:
            async for chunk in call_next():
                chunks += 1
                yield chunk
        finally:
            # Also runs when the client disconnects and the stream is closed early.
            logger.info("%s stream ended: %d chunks in %.1f ms", name, chunks, _elapsed_ms(started))


class ErrorBehavior:
    """Lets expected errors through; logs anything else once and wraps it in UnexpectedError."""

    async def handle(self, request: Request[Any], call_next: Next[Any]) -> Any:
        try:
            return await call_next()
        except EXPECTED_ERRORS:
            raise
        except Exception as error:
            raise _unexpected(request) from error

    async def handle_stream(
        self, request: StreamQuery[Any], call_next: StreamNext[Any]
    ) -> AsyncIterator[Any]:
        try:
            async for chunk in call_next():
                yield chunk
        except EXPECTED_ERRORS:
            raise
        except Exception as error:
            raise _unexpected(request) from error


def _unexpected(request: object) -> UnexpectedError:
    name = type(request).__name__
    logger.exception("Unexpected error while handling %s", name)
    return UnexpectedError(f"Unexpected error while handling {name}")
