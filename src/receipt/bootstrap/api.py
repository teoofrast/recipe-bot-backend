"""API entrypoint: ``uvicorn receipt.bootstrap.api:create_api --factory``."""

from fastapi import FastAPI

from receipt.application.mediator import Mediator
from receipt.bootstrap.container import build_container
from receipt.bootstrap.logs import configure_logging
from receipt.bootstrap.settings import Settings
from receipt.presentation.api.app import create_app

# Keys that protect nothing: empty, or the placeholder from .env.example.
_PLACEHOLDER_KEYS = {"", "change-me"}


class MissingApiKeyError(RuntimeError):
    pass


def create_api() -> FastAPI:
    container = build_container()
    settings = container.resolve(Settings)
    configure_logging(settings.log_level)
    api_key = settings.api_key.get_secret_value() if settings.api_key else ""
    if api_key in _PLACEHOLDER_KEYS:
        raise MissingApiKeyError(
            "API_KEY не задан или остался «change-me»: API не запускается без ключа. "
            "Сгенерируйте ключ (openssl rand -hex 32) и запишите в .env: API_KEY=..."
        )
    return create_app(container.resolve(Mediator), api_key)
