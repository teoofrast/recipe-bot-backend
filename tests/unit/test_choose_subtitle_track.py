from receipt.application.ports.video_downloader import SubtitleTrack
from receipt.application.video.subtitles import choose_subtitle_track, language_base


def track(language: str, automatic: bool = False) -> SubtitleTrack:
    return SubtitleTrack(
        language=language, url=f"https://subs/{language}", ext="vtt", automatic=automatic
    )


def test_language_base() -> None:
    assert language_base("en-US") == "en"
    assert language_base("en-orig") == "en"
    assert language_base("eng-US") == "en"
    assert language_base("rus-RU") == "ru"
    assert language_base("RU") == "ru"


def test_video_language_goes_first() -> None:
    tracks = [track("ru"), track("de")]

    assert choose_subtitle_track(tracks, ["ru", "en"], video_language="de") == track("de")


def test_preferred_languages_in_order_when_video_language_is_unknown() -> None:
    tracks = [track("de"), track("en-US"), track("ru")]

    assert choose_subtitle_track(tracks, ["ru", "en"], video_language=None) == track("ru")


def test_human_made_subtitles_beat_automatic_ones() -> None:
    tracks = [track("en", automatic=True), track("en")]

    assert choose_subtitle_track(tracks, ["en"], video_language="en") == track("en")


def test_automatic_subtitles_are_used_when_there_are_no_human_made_ones() -> None:
    tracks = [track("ru", automatic=True)]

    assert choose_subtitle_track(tracks, ["en"], video_language="ru") == track("ru", automatic=True)


def test_any_track_is_better_than_none() -> None:
    assert choose_subtitle_track([track("ja")], ["ru", "en"], video_language=None) == track("ja")


def test_no_tracks() -> None:
    assert choose_subtitle_track([], ["ru", "en"], video_language="ru") is None
