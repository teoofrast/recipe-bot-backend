from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from receipt.application.mediator import Mediator
from receipt.presentation.api.app import create_app

API_KEY = "test-key-0123456789"


@pytest.fixture
async def anonymous(mediator: Mediator) -> AsyncIterator[AsyncClient]:
    """A client without the API key."""
    transport = ASGITransport(app=create_app(mediator, api_key=API_KEY))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def client(anonymous: AsyncClient) -> AsyncIterator[AsyncClient]:
    anonymous.headers["X-API-Key"] = API_KEY
    yield anonymous
