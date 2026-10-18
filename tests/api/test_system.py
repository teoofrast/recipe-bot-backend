import json

import pytest
from httpx import AsyncClient


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
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


async def test_validation_errors_use_the_common_format(client: AsyncClient) -> None:
    response = await client.get("/ping/stream", params={"count": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "count" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/health"),
        ("GET", "/ping"),
        ("POST", "/imports"),
        ("GET", "/imports/abc"),
        ("GET", "/recipes"),
        ("GET", "/recipes/search?q=x"),
        ("GET", "/recipes/abc"),
        ("DELETE", "/recipes/abc"),
        ("POST", "/chat"),
        ("POST", "/chat/stream"),
        ("POST", "/admin/reindex"),
    ],
)
async def test_every_endpoint_needs_the_key(anonymous: AsyncClient, method: str, path: str) -> None:
    response = await anonymous.request(method, path)

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Нужен правильный заголовок X-API-Key"}
    }


async def test_a_wrong_key_is_refused(anonymous: AsyncClient) -> None:
    response = await anonymous.get("/health", headers={"X-API-Key": "test-key-0123456780"})

    assert response.status_code == 401


def test_openapi_lists_the_key_and_the_chat_stream_events(client: AsyncClient) -> None:
    app = client._transport.app  # type: ignore[attr-defined]
    schema = app.openapi()

    assert "APIKeyHeader" in schema["components"]["securitySchemes"]
    for name in ("TokenData", "ToolData", "SourcesData", "DoneData", "ErrorData"):
        assert name in schema["components"]["schemas"]
        assert "$defs" not in schema["components"]["schemas"][name]
    assert (
        "text/event-stream"
        in schema["paths"]["/chat/stream"]["post"]["responses"]["200"]["content"]
    )
