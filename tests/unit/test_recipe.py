import pytest

from receipt.domain.recipe import (
    Ingredient,
    InvalidRecipeError,
    Recipe,
    RecipeSource,
    normalize_unit,
)
from receipt.domain.video import Platform

SOURCE = RecipeSource(url="https://youtu.be/x", platform=Platform.YOUTUBE, video_id="x")


@pytest.mark.parametrize(
    ("raw", "unit"),
    [
        ("г", "г"),
        ("гр.", "г"),
        ("Граммов", "г"),
        ("g", "г"),
        ("кг", "кг"),
        ("ml", "мл"),
        ("шт.", "шт"),
        ("ст. л.", "ст. л."),
        ("ст.л.", "ст. л."),
        ("столовые ложки", "ст. л."),
        ("Tbsp", "ст. л."),
        ("столовую ложку", "ст. л."),
        ("ч. л.", "ч. л."),
        ("чайной ложки", "ч. л."),
        ("tsp", "ч. л."),
        ("чайную ложку", "ч. л."),
        ("стакана", "стакан"),
        ("cups", "стакан"),
        ("щепотка", "щепотка"),
        ("зубчика", "зубчик"),
        ("пучок", "пучок"),
        ("банка", "банка"),  # unknown units are kept
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_unit(raw: str | None, unit: str | None) -> None:
    assert normalize_unit(raw) == unit


def test_ingredient_is_normalized() -> None:
    ingredient = Ingredient(name="  творог   9% ", amount=400, unit="гр.", note=" ")

    assert ingredient == Ingredient(name="творог 9%", amount=400, unit="г", note=None)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": " "}, "нет названия"),
        ({"name": "мука", "amount": 0}, "Неверное количество"),
        ({"name": "мука", "amount": -1}, "Неверное количество"),
    ],
)
def test_invalid_ingredients(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidRecipeError, match=message):
        Ingredient(**kwargs)  # type: ignore[arg-type]


def test_recipe_is_cleaned_up() -> None:
    recipe = Recipe(
        title=" Сырники ",
        ingredients=(Ingredient("творог", 400, "г"),),
        steps=(" Смешать ", "", "Обжарить"),
        source=SOURCE,
        tags=("Завтрак", "завтрак ", " ", "сладкое"),
    )

    assert recipe.title == "Сырники"
    assert recipe.steps == ("Смешать", "Обжарить")
    assert recipe.tags == ("завтрак", "сладкое")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"title": " "}, "нет названия"),
        ({"ingredients": ()}, "нет ингредиентов"),
        ({"servings": 0}, "порций"),
        ({"total_minutes": -5}, "время"),
    ],
)
def test_invalid_recipes(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "title": "Сырники",
        "ingredients": (Ingredient("творог"),),
        "steps": (),
        "source": SOURCE,
        **kwargs,
    }

    with pytest.raises(InvalidRecipeError, match=message):
        Recipe(**values)  # type: ignore[arg-type]
