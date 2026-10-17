from collections.abc import Sequence

from receipt.application.ports.video_downloader import SubtitleTrack

# TikTok uses three-letter codes ("eng-US", "rus-RU").
_ALIASES = {"eng": "en", "rus": "ru"}


def language_base(code: str) -> str:
    """Base language code: "en-US", "en-orig", "eng-US" -> "en"."""
    base = code.split("-")[0].lower()
    return _ALIASES.get(base, base)


def choose_subtitle_track(
    tracks: Sequence[SubtitleTrack], preferred: Sequence[str], video_language: str | None
) -> SubtitleTrack | None:
    """The video's own language first, then ``preferred``; human-made before automatic.

    If nothing matches, any track is still better than transcribing the audio.
    """
    codes = [video_language, *preferred] if video_language else list(preferred)
    order = list(dict.fromkeys(language_base(code) for code in codes))
    manual = [track for track in tracks if not track.automatic]
    automatic = [track for track in tracks if track.automatic]
    for group in (manual, automatic):
        for language in order:
            for track in group:
                if language_base(track.language) == language:
                    return track
    return next(iter(manual or automatic), None)
