"""API entrypoint: ``uvicorn receipt.bootstrap.api:create_api --factory``."""

from fastapi import FastAPI

from receipt.application.mediator import Mediator
from receipt.bootstrap.container import build_container
from receipt.bootstrap.logs import configure_logging
from receipt.bootstrap.settings import Settings
from receipt.presentation.api.app import create_app


def create_api() -> FastAPI:
    container = build_container()
    configure_logging(container.resolve(Settings).log_level)
    return create_app(container.resolve(Mediator))
