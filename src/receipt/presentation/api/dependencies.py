from typing import Annotated

from fastapi import Depends, Request

from receipt.application.mediator import Mediator


def get_mediator(request: Request) -> Mediator:
    return request.app.state.mediator


MediatorDep = Annotated[Mediator, Depends(get_mediator)]
