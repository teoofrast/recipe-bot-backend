from enum import StrEnum
from urllib.parse import urlparse

from receipt.domain.errors import DomainError


class Platform(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class UnsupportedUrlError(DomainError):
    """The link is not a single video on a supported platform."""


_DOMAINS = {
    Platform.YOUTUBE: ("youtube.com", "youtu.be"),
    Platform.TIKTOK: ("tiktok.com",),
    Platform.INSTAGRAM: ("instagram.com",),
}


def detect_platform(url: str) -> Platform:
    """Supported: YouTube (videos and Shorts), TikTok, Instagram (Reels and posts)."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme in ("http", "https") and host:
        for platform, domains in _DOMAINS.items():
            if any(host == domain or host.endswith(f".{domain}") for domain in domains):
                return platform
    raise UnsupportedUrlError(
        f"Ссылка не поддерживается: {url}. Нужно видео с YouTube, TikTok или Instagram."
    )
