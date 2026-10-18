"""Recipe extraction with an LLM: a JSON schema for the model, mapped onto the domain Recipe."""

import logging
import re

from pydantic import BaseModel, Field

from receipt.domain.recipe import (
    Ingredient,
    InvalidRecipeError,
    Recipe,
    RecipeSource,
    normalize_unit,
)
from receipt.domain.source_text import SourceText
from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose, translate_llm_errors

logger = logging.getLogger(__name__)

# Field descriptions go into the JSON schema the model sees: they are part of the prompt.


class ExtractedIngredient(BaseModel):
    name: str = Field(
        description="Продукт на русском, в именительном падеже, без количества: «яйцо», "
        "а не «2 яйца»; «творог 5%», «сливочное масло». Английское переводи: eggs → яйца"
    )
    amount: float | None = Field(
        description="Количество числом: 400, 2, 0.5. Для диапазона «2–3» — меньшее число, "
        "а сам диапазон — в note. null, если в тексте не указано"
    )
    unit: str | None = Field(
        description="Единица: г, кг, мл, л, шт, ст. л., ч. л., стакан, щепотка, зубчик, пучок. "
        "Только вместе с amount. null, если её нет («2 яйца» → amount 2, unit null)"
    )
    note: str | None = Field(
        description="Уточнение из текста: «по вкусу», «для жарки», «комнатной температуры». "
        "null, если нет"
    )


class ExtractedRecipe(BaseModel):
    has_recipe: bool = Field(
        description="true, только если в тексте есть рецепт: блюдо и из чего его готовят. "
        "false для влогов, обзоров, рекламы, шуток, музыки без слов, одного названия блюда"
    )
    title: str | None = Field(
        description="Короткое название блюда на русском, как его назвал бы повар: «Сырники», "
        "«Паста карбонара». Без капса, эмодзи, хэштегов, имени автора и рекламных слов "
        "(«идеальные», «от шефа», «видео рецепт»)"
    )
    servings: int | None = Field(
        description="Число порций или едоков, только если сказано «на N порций/человек». "
        "Количество штук (12 сырников) — не порции"
    )
    total_minutes: int | None = Field(
        description="Общее время приготовления в минутах, только если оно названо в тексте"
    )
    ingredients: list[ExtractedIngredient] = Field(
        description="Все продукты из текста, каждый отдельно, в порядке упоминания"
    )
    steps: list[str] = Field(
        description="Шаги на русском, по порядку, коротко, в повелительном наклонении: "
        "«Отожмите творог через марлю». Без приветствий и рекламы. Пусто, если шагов в тексте нет"
    )
    cuisine: str | None = Field(
        description="Кухня строчными буквами, если очевидна: русская, итальянская..."
    )
    tags: list[str] = Field(
        description="1–5 общих категорий на русском строчными: завтрак, десерт, суп, выпечка, "
        "без мяса, быстро. Не копируй хэштеги из описания"
    )


SYSTEM_PROMPT = """Ты извлекаешь кулинарный рецепт из текста видео: названия, описания автора, \
субтитров или автоматически распознанной речи.

Правила:
1. Бери только то, что есть в тексте. Не придумывай ингредиенты, количества, шаги, порции и \
время. Чего нет в тексте — оставляй null.
2. Если рецепта нет (влог, обзор, реклама, шутка, музыка без слов, только название блюда без \
ингредиентов) — has_recipe=false, остальные поля пустые.
3. Ингредиенты: каждый продукт отдельно. Количество — числом, единица — отдельно. Продукт, \
который упомянут только в шагах («жарю на масле»), тоже добавь, без количества.
4. Все поля — на русском, даже если видео на английском или другом языке: переводи названия \
продуктов и шаги.
5. В распознанной речи бывают ошибки — исправляй очевидные («творок» → «творог»).
6. Теги и кухню можно определить по смыслу; всё остальное — только из текста.

Пример названия и тегов. Заголовок видео «САМЫЕ НЕЖНЫЕ БЛИНЫ НА МОЛОКЕ // Рецепт с дырочками \
от бабушки #блинырецепт» → title «Блины на молоке», tags [«завтрак», «выпечка»]. \
«Получилось 20 блинов» — это не 20 порций: servings=null."""


class LlmRecipeExtractor:
    def __init__(self, provider: ChatModelProvider) -> None:
        self._provider = provider

    async def extract(self, text: SourceText, source: RecipeSource) -> Recipe | None:
        content = text.combined()
        if not content:
            return None
        chain = self._provider.with_fallbacks(
            Purpose.EXTRACT,
            lambda model: model.with_structured_output(ExtractedRecipe, method="json_schema"),
        )
        with translate_llm_errors():
            extracted: ExtractedRecipe = await chain.ainvoke(
                [("system", SYSTEM_PROMPT), ("user", content)]
            )
        return to_recipe(extracted, source, content)


MAX_TAGS = 5
# "столовую ложку" with no number means one.
_SINGLE_MEASURES = {"ст. л.", "ч. л.", "стакан", "щепотка", "зубчик", "пучок"}


def _to_ingredient(item: ExtractedIngredient) -> Ingredient:
    # "0 г" means "not stated" coming from a model, not zero grams.
    amount = item.amount if item.amount and item.amount > 0 else None
    unit, note = normalize_unit(item.unit), item.note
    if amount is None and unit is not None:
        if unit in _SINGLE_MEASURES:
            amount = 1
        else:
            # A unit without a number ("2–3 шт.", "г") is not a quantity; keep it as a remark.
            note = ", ".join(part for part in (unit, note) if part)
            unit = None
    return Ingredient(name=item.name, amount=amount, unit=unit, note=note)


def clean_title(title: str) -> str:
    """Models copy video titles as they are: "ПЫШНЫЕ СЫРНИКИ // Идеальный рецепт #Shorts"."""
    title = re.sub(r"#\S+", "", title)
    title = re.split(r"\s(?:\||//|—)\s", title)[0].strip(" .!|/—-")
    letters = [char for char in title if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.6:
        title = title.lower()
    return title[:1].upper() + title[1:]


def clean_tags(tags: list[str], source_text: str) -> tuple[str, ...]:
    """Drops hashtags copied from the description ("сырникирецепт"); keeps the first few."""
    hashtags = {match.lower() for match in re.findall(r"#(\w+)", source_text)}
    kept = [tag.lstrip("#").strip() for tag in tags]
    return tuple(tag for tag in kept if tag and tag.lower() not in hashtags)[:MAX_TAGS]


def to_recipe(
    extracted: ExtractedRecipe, source: RecipeSource, source_text: str = ""
) -> Recipe | None:
    """None when the model found no recipe or returned one the domain does not accept."""
    if not extracted.has_recipe:
        return None
    ingredients = []
    for item in extracted.ingredients:
        try:
            ingredients.append(_to_ingredient(item))
        except InvalidRecipeError:
            logger.info("Skipped an invalid ingredient: %s", item)
    try:
        return Recipe(
            title=clean_title(extracted.title or ""),
            ingredients=tuple(ingredients),
            steps=tuple(extracted.steps),
            source=source,
            servings=extracted.servings if extracted.servings and extracted.servings > 0 else None,
            total_minutes=extracted.total_minutes
            if extracted.total_minutes and extracted.total_minutes > 0
            else None,
            cuisine=extracted.cuisine.strip().lower() if extracted.cuisine else None,
            tags=clean_tags(extracted.tags, source_text),
        )
    except InvalidRecipeError as error:
        logger.info("The model's recipe was rejected: %s", error)
        return None
