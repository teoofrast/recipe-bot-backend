import pytest

from receipt.domain.source_text import SourceText, looks_like_ingredient_list

INGREDIENTS = """Борщ на 4 порции:
свёкла 2 шт
капуста 300 г
картофель 400 гр
томатная паста 2 ст. л.
"""


@pytest.mark.parametrize(
    "text",
    [
        INGREDIENTS,
        "Flour 200 g, milk 250 ml, sugar 2 tbsp",
        "мука 1,5 стакана; соль 1 ч.л.; чеснок 2 зубчика",
        "1/2 tsp salt, 3 cups water, 2 cloves garlic",
    ],
)
def test_detects_ingredient_lists(text: str) -> None:
    assert looks_like_ingredient_list(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Самый вкусный борщ! Подписывайтесь 🙌",
        "Запекать 40 минут при 180 градусах",  # numbers, but no ingredients
        "HAPPY NEW 2026",
        "мука 200 г и всё",  # one quantity is not a list
    ],
)
def test_ignores_texts_without_ingredient_lists(text: str) -> None:
    assert not looks_like_ingredient_list(text)


def test_subtitles_are_enough_without_transcription() -> None:
    text = SourceText(title="Борщ", description="Подписывайтесь!", subtitles="Берём свёклу...")

    assert text.has_subtitles
    assert not text.needs_transcription


def test_ingredient_list_in_description_is_enough_without_transcription() -> None:
    assert not SourceText(title="Борщ", description=INGREDIENTS).needs_transcription


def test_no_subtitles_and_no_ingredients_needs_transcription() -> None:
    text = SourceText(title="Борщ", description="Рецепт в видео 👇", subtitles="   ")

    assert not text.has_subtitles
    assert text.needs_transcription


def test_combined_text_has_labelled_non_empty_sections() -> None:
    text = SourceText(title="Борщ", description="", subtitles="Берём свёклу")

    assert text.combined() == "Название:\nБорщ\n\nСубтитры:\nБерём свёклу"
