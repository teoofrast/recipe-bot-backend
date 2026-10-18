from enum import StrEnum


class ApplicationError(Exception):
    """An expected failure of a use case (not found, duplicate, external service down...)."""


class UnexpectedError(ApplicationError):
    """Anything a handler did not expect. The original exception is kept in ``__cause__``."""


class VideoUnavailableReason(StrEnum):
    PRIVATE = "private"
    NOT_FOUND = "not_found"
    GEO_BLOCKED = "geo_blocked"
    LOGIN_REQUIRED = "login_required"
    UNKNOWN = "unknown"


_REASON_TEXT = {
    VideoUnavailableReason.PRIVATE: "видео приватное",
    VideoUnavailableReason.NOT_FOUND: "видео удалено или не существует",
    VideoUnavailableReason.GEO_BLOCKED: "видео недоступно в этой стране",
    VideoUnavailableReason.LOGIN_REQUIRED: "платформа требует входа в аккаунт (нужны cookies)",
    VideoUnavailableReason.UNKNOWN: "платформа не отдала видео",
}


class RecipeNotFoundError(ApplicationError):
    def __init__(self, recipe_id: str) -> None:
        super().__init__(f"Рецепт {recipe_id} не найден")
        self.recipe_id = recipe_id


class ImportJobNotFoundError(ApplicationError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"Импорт {job_id} не найден")
        self.job_id = job_id


class DuplicateRecipeError(ApplicationError):
    """A recipe from this video is already saved."""

    def __init__(self, source_key: str) -> None:
        super().__init__(f"Рецепт из этого видео уже сохранён ({source_key})")
        self.source_key = source_key


class SearchUnavailableError(ApplicationError):
    """The search index or the embeddings service does not answer."""


class LlmUnavailableError(ApplicationError):
    """No language model answered: wrong key, every model failed or hit its limit."""


class TranscriptionError(ApplicationError):
    """Speech could not be turned into text: no API key, no credits, every model failed."""


class FramesUnavailableError(ApplicationError):
    """The video's frames could not be taken (ffmpeg failed or the video has no picture)."""


class SubtitlesUnavailableError(ApplicationError):
    """A subtitle track is listed but could not be downloaded."""


class VideoUnavailableError(ApplicationError):
    """The platform would not give the video. ``detail`` keeps the platform's own message."""

    def __init__(self, reason: VideoUnavailableReason, detail: str = "") -> None:
        super().__init__(f"Не удалось получить видео: {_REASON_TEXT[reason]}")
        self.reason = reason
        self.detail = detail
