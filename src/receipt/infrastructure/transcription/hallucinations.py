import re

# Whisper was trained on subtitles from the internet, so over music or silence it "hears" the
# credits that used to end those subtitles. Seen on real recipe Reels with background music.
_PHRASES = re.compile(
    r"[^.!?…]*(?:"
    r"DimaTorzok"
    r"|Субтитры\s+(?:сделал|создавал|подогнал|делал|подготовил)"
    r"|Редактор\s+субтитров"
    r"|Корректор\s+[А-ЯЁ]\.\s*[А-ЯЁ]"
    r"|Продолжение\s+следует"
    r"|Спасибо\s+за\s+просмотр"
    r"|Подписывайтесь\s+на\s+канал"
    r"|ДИНАМИЧНАЯ\s+МУЗЫКА|СПОКОЙНАЯ\s+МУЗЫКА|ВЕСЁЛАЯ\s+МУЗЫКА"
    r"|Amara\.org"
    r"|Thanks?\s+(?:you\s+)?for\s+watching"
    r")[^.!?…]*(?:\.{3}|[.!?…»]+)?",
    re.IGNORECASE,
)


def remove_hallucinations(text: str) -> str:
    """Drops sentences that are known Whisper hallucinations; real speech is left as is."""
    return " ".join(_PHRASES.sub(" ", text).split())
