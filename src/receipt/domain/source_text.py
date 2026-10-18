import re
from dataclasses import dataclass

# "200 г", "1,5 л", "2 ст. л.", "1/2 tsp", "3 cups"... The lookahead keeps "г" from matching
# the start of a word like "градусов".
_QUANTITY = re.compile(
    r"\d+(?:[.,/]\d+)?\s*"
    r"(?:кг|гр|г|мл|л|шт|ст\.?\s*л|ч\.?\s*л|стакан\w*|зубч\w*|щепот\w*|пуч\w*"
    r"|kg|g|ml|l|pcs|tbsp|tsp|cups?|oz|lb|cloves?)"
    r"(?![a-zа-яё])",
    re.IGNORECASE,
)

# Three quantities in a row is already an ingredient list, not a random number in a caption.
MIN_QUANTITIES = 3
# Fewer words is the platform's noise ("foreign" for music), not speech that holds a recipe.
MIN_SUBTITLE_WORDS = 5


# "0:17 Making the pancakes", "1:02:03 - Соус": YouTube chapters. Models turn them into steps
# ("Приготовьте блины"), which hides that the method itself is missing.
_CHAPTER = re.compile(r"^[^\w\n]*\d{1,2}:\d{2}(?::\d{2})?\b.*$\n?", re.MULTILINE)


def without_chapters(text: str) -> str:
    return _CHAPTER.sub("", text)


def looks_like_ingredient_list(text: str) -> bool:
    return len(_QUANTITY.findall(text)) >= MIN_QUANTITIES


@dataclass(frozen=True)
class SourceText:
    """Everything the video says in text form, before the recipe is extracted from it."""

    title: str
    description: str
    subtitles: str = ""
    # Speech recognized from the audio, when subtitles and description were not enough.
    transcript: str = ""
    # What a vision model saw on the video's frames: on-screen text and the cook's actions.
    frames: str = ""

    @property
    def has_subtitles(self) -> bool:
        return len(self.subtitles.split()) >= MIN_SUBTITLE_WORDS

    @property
    def needs_transcription(self) -> bool:
        """Only speech is left: no subtitles, and the description lists no ingredients."""
        return not self.has_subtitles and not looks_like_ingredient_list(self.description)

    def combined(self) -> str:
        sections = (
            ("Название", self.title),
            ("Описание", without_chapters(self.description)),
            ("Субтитры", self.subtitles),
            ("Речь из видео (распознана автоматически)", self.transcript),
            ("Что видно на кадрах видео (описано автоматически)", self.frames),
        )
        return "\n\n".join(
            f"{label}:\n{value.strip()}" for label, value in sections if value.strip()
        )
