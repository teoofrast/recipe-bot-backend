# ruff: noqa: E501  (real subtitle samples have long lines)
from receipt.infrastructure.video.subtitles import subtitles_to_text

# A real excerpt of YouTube automatic captions: every line rolls over into the next cue.
YOUTUBE_AUTO_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.320 --> 00:00:18.790 align:start position:0%

[Music]

00:00:18.790 --> 00:00:18.800 align:start position:0%



00:00:18.800 --> 00:00:21.790 align:start position:0%

We're<00:00:19.039><c> no</c><00:00:19.359><c> strangers</c><00:00:19.840><c> to</c>

00:00:21.790 --> 00:00:21.800 align:start position:0%
We're no strangers to


00:00:21.800 --> 00:00:25.950 align:start position:0%
We're no strangers to
love.<00:00:22.800><c> You</c><00:00:23.039><c> know</c><00:00:23.279><c> the</c><00:00:23.600><c> rules</c>

00:00:25.950 --> 00:00:25.960 align:start position:0%
love. You know the rules

"""

MANUAL_VTT = """WEBVTT
Kind: captions
Language: ru

NOTE made by hand

00:00:01.360 --> 00:00:03.040
[♪♪♪]

00:00:03.640 --> 00:00:06.880
♪ Берём 200 г муки ♪

00:00:07.040 --> 00:00:09.960
и 2 яйца,
<i>взбиваем</i> &amp; солим
"""

SRT = """1
00:00:01,000 --> 00:00:02,500
Нарезаем лук

2
00:00:02,600 --> 00:00:04,000
и обжариваем 5 минут
"""


def test_youtube_rolling_captions_lose_timings_tags_and_repeats() -> None:
    assert subtitles_to_text(YOUTUBE_AUTO_VTT) == "We're no strangers to love. You know the rules"


def test_manual_vtt_drops_notes_music_marks_and_html() -> None:
    assert subtitles_to_text(MANUAL_VTT) == "Берём 200 г муки и 2 яйца, взбиваем & солим"


def test_srt_is_supported() -> None:
    assert subtitles_to_text(SRT) == "Нарезаем лук и обжариваем 5 минут"


def test_a_line_of_only_a_number_is_taken_for_a_cue_index() -> None:
    # Known limitation: SRT cue indexes and VTT cue ids are bare numbers, so a subtitle line
    # that is only a number is dropped. Numbers inside text are kept.
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n200\n\n00:00:02.000 --> 00:00:03.000\nграммов\n"

    assert subtitles_to_text(vtt) == "граммов"


def test_empty_input_gives_empty_text() -> None:
    assert subtitles_to_text("") == ""
    assert subtitles_to_text("WEBVTT\n\n") == ""


def test_youtube_noise_markers_are_not_text() -> None:
    raw = "WEBVTT\n\n00:00:00.960 --> 00:00:33.840\n[Music]\n\n00:00:42.000 --> 00:00:44.079\nforeign\n"

    assert subtitles_to_text(raw) == ""
