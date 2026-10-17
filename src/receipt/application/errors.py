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


class SubtitlesUnavailableError(ApplicationError):
    """A subtitle track is listed but could not be downloaded."""


class VideoUnavailableError(ApplicationError):
    """The platform would not give the video. ``detail`` keeps the platform's own message."""

    def __init__(self, reason: VideoUnavailableReason, detail: str = "") -> None:
        super().__init__(f"Не удалось получить видео: {_REASON_TEXT[reason]}")
        self.reason = reason
        self.detail = detail
