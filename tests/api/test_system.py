import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from receipt.application.mediator import Mediator
from receipt.presentation.api.app import create_app


@pytest.fixture
async def client(mediator: Mediator) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app(mediator))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def parse_sse(body: str) -> list[tuple[str, dict[str, str]]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ping_returns_pong_from_fake_clock(client: AsyncClient) -> None:
    response = await client.get("/ping")

    assert response.status_code == 200
    assert response.json() == {"message": "pong", "at": "2026-01-01T12:00:00Z"}


async def test_ping_stream_sends_each_chunk_as_sse_event(client: AsyncClient) -> None:
    response = await client.get("/ping/stream", params={"count": 2})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert parse_sse(response.text) == [
        ("pong", {"message": "pong 1", "at": "2026-01-01T12:00:00Z"}),
        ("pong", {"message": "pong 2", "at": "2026-01-01T12:00:00Z"}),
    ]


async def test_ping_stream_validates_count(client: AsyncClient) -> None:
    response = await client.get("/ping/stream", params={"count": 0})

    assert response.status_code == 422
