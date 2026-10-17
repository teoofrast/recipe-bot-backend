from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from receipt.application.system.ping import Ping, PingStream, Pong
from receipt.presentation.api.dependencies import MediatorDep

router = APIRouter(tags=["system"])


class PongResponse(BaseModel):
    message: str
    at: datetime

    @classmethod
    def from_pong(cls, pong: Pong) -> "PongResponse":
        return cls(message=pong.message, at=pong.at)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ping")
async def ping(mediator: MediatorDep) -> PongResponse:
    return PongResponse.from_pong(await mediator.send(Ping()))


@router.get("/ping/stream")
async def ping_stream(
    mediator: MediatorDep, count: Annotated[int, Query(ge=1, le=100)] = 3
) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        async for pong in mediator.stream(PingStream(count=count)):
            yield {"event": "pong", "data": PongResponse.from_pong(pong).model_dump_json()}

    return EventSourceResponse(events())
