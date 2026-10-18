"""One error format for every endpoint: {"error": {"code": ..., "message": ...}}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from receipt.application.errors import (
    ApplicationError,
    DuplicateRecipeError,
    ImportJobNotFoundError,
    LlmUnavailableError,
    RecipeNotFoundError,
    SearchUnavailableError,
    TranscriptionError,
    UnexpectedError,
    VideoUnavailableError,
)
from receipt.domain.errors import DomainError

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# Most specific first: the first matching class wins.
_STATUS: list[tuple[type[Exception], int, str]] = [
    (RecipeNotFoundError, 404, "recipe_not_found"),
    (ImportJobNotFoundError, 404, "import_not_found"),
    (DuplicateRecipeError, 409, "duplicate_recipe"),
    (VideoUnavailableError, 502, "video_unavailable"),
    (LlmUnavailableError, 503, "llm_unavailable"),
    (SearchUnavailableError, 503, "search_unavailable"),
    (TranscriptionError, 503, "transcription_unavailable"),
    (UnexpectedError, 500, "internal_error"),
    (DomainError, 422, "invalid_request"),  # unsupported link, invalid recipe...
    (ApplicationError, 400, "bad_request"),
]


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def status_for(error: Exception) -> tuple[int, str]:
    for error_type, status, code in _STATUS:
        if isinstance(error, error_type):
            return status, code
    return 500, "internal_error"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status, error.code, error.message)

    @app.exception_handler(DomainError)
    @app.exception_handler(ApplicationError)
    async def app_error(request: Request, error: Exception) -> JSONResponse:
        status, code = status_for(error)
        # Internal details stay in the log (ErrorBehavior logged the traceback).
        message = "Внутренняя ошибка" if status == 500 else str(error)
        return error_response(status, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'][1:])}: {item['msg']}"
            for item in error.errors()
        )
        return error_response(422, "validation_error", details or "Неверный запрос")
