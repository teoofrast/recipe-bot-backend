import html
import re

_TAG = re.compile(r"<[^>]*>")
_HEADER_PREFIXES = ("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")
_NOISE = re.compile(r"^\[[^\]]*\]$")  # [Music], [Музыка], [♪♪♪]


def subtitles_to_text(raw: str) -> str:
    """WebVTT or SRT -> plain text: no headers, cue numbers, timings, tags or repeats.

    YouTube's automatic captions "roll": every line is shown again at the top of the next cue,
    so a line equal to the previous one is a repeat and is dropped.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(_HEADER_PREFIXES) or "-->" in line or line.isdigit():
            continue
        text = html.unescape(_TAG.sub("", line)).replace("♪", "").strip()
        text = " ".join(text.split())
        if not text or _NOISE.match(text):
            continue
        if not lines or lines[-1] != text:
            lines.append(text)
    return " ".join(lines)
