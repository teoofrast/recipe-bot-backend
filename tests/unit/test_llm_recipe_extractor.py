from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda

from receipt.domain.recipe import Ingredient, RecipeSource
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose
from receipt.infrastructure.recipes.llm_extractor import (
    SYSTEM_PROMPT,
    ExtractedIngredient,
    ExtractedRecipe,
    LlmRecipeExtractor,
    clean_tags,
    clean_title,
    to_recipe,
)

SOURCE = RecipeSource(
    url="https://youtu.be/x", platform=Platform.YOUTUBE, video_id="x", author="chef"
)


def extracted(**overrides: Any) -> ExtractedRecipe:
    values: dict[str, Any] = {
        "has_recipe": True,
        "title": "Сырники",
        "servings": 2,
        "total_minutes": 30,
        "ingredients": [ExtractedIngredient(name="творог", amount=400, unit="гр", note=None)],
        "steps": ["Смешайте", "Обжарьте"],
        "cuisine": "Русская",
        "tags": ["завтрак"],
        **overrides,
    }
    return ExtractedRecipe(**values)


def ingredient(**overrides: Any) -> ExtractedIngredient:
    return ExtractedIngredient(
        **{"name": "мука", "amount": None, "unit": None, "note": None, **overrides}
    )


class FakeStructuredModel:
    """Plays a chat model: with_structured_output returns a step answering ``answer``."""

    def __init__(self, answer: ExtractedRecipe) -> None:
        self.answer = answer
        self.messages: list[Any] = []
        self.schema: Any = None
        self.method: str | None = None

    def with_structured_output(self, schema: Any, method: str) -> RunnableLambda[Any, Any]:
        self.schema, self.method = schema, method

        def answer(messages: Any) -> ExtractedRecipe:
            self.messages = messages
            return self.answer

        return RunnableLambda(answer)


def make_extractor(model: FakeStructuredModel) -> LlmRecipeExtractor:
    provider = ChatModelProvider(
        api_key="sk-test",
        models={Purpose.EXTRACT: ["m"]},
        model_factory=lambda model_id, timeout: model,  # type: ignore[arg-type,return-value]
    )
    return LlmRecipeExtractor(provider)


async def test_extractor_sends_prompt_and_text_and_maps_the_answer() -> None:
    model = FakeStructuredModel(extracted())
    text = SourceText(title="Сырники", description="творог 400 г", subtitles="Смешиваем")

    recipe = await make_extractor(model).extract(text, SOURCE)

    assert model.schema is ExtractedRecipe
    assert model.method == "json_schema"
    assert model.messages == [("system", SYSTEM_PROMPT), ("user", text.combined())]
    assert recipe is not None
    assert recipe.title == "Сырники"
    assert recipe.ingredients == (Ingredient("творог", 400, "г"),)
    assert recipe.source == SOURCE


async def test_empty_text_is_not_sent_to_the_model() -> None:
    model = FakeStructuredModel(extracted())

    assert await make_extractor(model).extract(SourceText(title="", description=""), SOURCE) is None
    assert model.messages == []


def test_no_recipe_answer_gives_none() -> None:
    assert to_recipe(extracted(has_recipe=False), SOURCE) is None


def test_recipe_the_domain_rejects_gives_none() -> None:
    assert to_recipe(extracted(ingredients=[]), SOURCE) is None
    assert to_recipe(extracted(title=" "), SOURCE) is None


def test_invalid_ingredients_are_skipped() -> None:
    recipe = to_recipe(
        extracted(
            ingredients=[ingredient(name=" "), ingredient(name="мука", amount=200, unit="г")]
        ),
        SOURCE,
    )

    assert recipe is not None
    assert recipe.ingredients == (Ingredient("мука", 200, "г"),)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        # "0" from a model means "not stated".
        (ingredient(amount=0, unit=None), Ingredient("мука")),
        # "столовую ложку" without a number is one spoon.
        (ingredient(unit="ст. л."), Ingredient("мука", 1, "ст. л.")),
        (ingredient(unit="чайную ложку"), Ingredient("мука", 1, "ч. л.")),
        # A unit without a number that is not a measure is kept as a remark.
        (ingredient(unit="2–3 шт.", note=None), Ingredient("мука", note="2–3 шт.")),
        (ingredient(unit="г", note="по вкусу"), Ingredient("мука", note="г, по вкусу")),
    ],
)
def test_quantities_from_the_model_are_made_consistent(
    item: ExtractedIngredient, expected: Ingredient
) -> None:
    recipe = to_recipe(extracted(ingredients=[item]), SOURCE)

    assert recipe is not None
    assert recipe.ingredients == (expected,)


def test_non_positive_servings_and_time_are_dropped() -> None:
    recipe = to_recipe(extracted(servings=0, total_minutes=-1), SOURCE)

    assert recipe is not None
    assert (recipe.servings, recipe.total_minutes) == (None, None)


def test_tags_and_cuisine_are_tidied() -> None:
    tags = ["#Завтрак", "сладкое", "творог", "быстро", "сковорода", "пп", "десерт"]

    recipe = to_recipe(extracted(tags=tags, cuisine=" Русская "), SOURCE)

    assert recipe is not None
    assert recipe.tags == ("завтрак", "сладкое", "творог", "быстро", "сковорода")
    assert recipe.cuisine == "русская"


@pytest.mark.parametrize(
    ("raw", "title"),
    [
        (
            "ПЫШНЫЕ СЫРНИКИ, КОТОРЫЕ НЕ РАСТЕКАЮТСЯ // Творожные Сырники",
            "Пышные сырники, которые не растекаются",
        ),
        ("Борщ видео рецепт | простые рецепты от Дании", "Борщ видео рецепт"),
        (
            "Идеальные сырники на завтрак. Без муки. #Shorts",
            "Идеальные сырники на завтрак. Без муки",
        ),
        ("ПАСТА КАРБОНАРА ОТ ШЕФА ИВЛЕВА", "Паста карбонара от шефа ивлева"),
        ("Паста карбонара", "Паста карбонара"),
        ("сырники", "Сырники"),
    ],
)
def test_clean_title(raw: str, title: str) -> None:
    assert clean_title(raw) == title


def test_hashtags_from_the_description_are_not_tags() -> None:
    description = "Рецепт сырников #сырникирецепт #назавтрак #творог"

    tags = clean_tags(["сырникирецепт", "#назавтрак", "завтрак", "творог", "выпечка"], description)

    assert tags == ("завтрак", "выпечка")
