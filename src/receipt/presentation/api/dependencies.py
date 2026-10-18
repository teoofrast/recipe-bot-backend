import asyncio
from typing import Annotated

from fastapi import Depends, Request

from receipt.application.mediator import Mediator


def get_mediator(request: Request) -> Mediator:
    return request.app.state.mediator


def get_background_tasks(request: Request) -> set[asyncio.Task[object]]:
    """Running imports: kept referenced (an unreferenced task may be garbage-collected)."""
    return request.app.state.background_tasks


MediatorDep = Annotated[Mediator, Depends(get_mediator)]
BackgroundTasksDep = Annotated[set[asyncio.Task[object]], Depends(get_background_tasks)]
