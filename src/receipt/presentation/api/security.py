import secrets
from collections.abc import Awaitable, Callable

from fastapi import Security
from fastapi.security import APIKeyHeader

from receipt.presentation.api.errors import ApiError

API_KEY_HEADER = "X-API-Key"
# Swagger shows an "Authorize" button for this scheme.
_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False, description="Ключ из API_KEY")


def api_key_guard(expected: str) -> Callable[..., Awaitable[None]]:
    """A dependency that lets a request through only with the right X-API-Key."""
    expected_bytes = expected.encode()

    async def verify_api_key(key: str | None = Security(_header)) -> None:
        # compare_digest: the time taken does not tell how much of the key was right.
        if key is None or not secrets.compare_digest(key.encode(), expected_bytes):
            raise ApiError(401, "unauthorized", f"Нужен правильный заголовок {API_KEY_HEADER}")

    return verify_api_key
