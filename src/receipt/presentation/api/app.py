from fastapi import FastAPI

from receipt.application.mediator import Mediator
from receipt.presentation.api.routers import system


def create_app(mediator: Mediator) -> FastAPI:
    app = FastAPI(title="Recipe Bot API")
    app.state.mediator = mediator
    app.include_router(system.router)
    return app
