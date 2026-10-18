import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime

from receipt.domain.errors import DomainError
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform


class InvalidRecipeError(DomainError):
    """The data does not make a usable recipe (no title, no ingredients...)."""


# Spellings seen in recipes and model answers -> one canonical unit.
_UNIT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "г": ("г", "гр", "грамм", "грамма", "граммов", "g", "gr", "gram", "grams"),
    "кг": ("кг", "килограмм", "килограмма", "килограммов", "kg"),
    "мл": ("мл", "миллилитр", "миллилитра", "миллилитров", "ml"),
    "л": ("л", "литр", "литра", "литров", "l", "liter", "liters", "litre"),
    "шт": ("шт", "штука", "штуки", "штук", "pcs", "pc", "piece", "pieces"),
    "ст. л.": (
        "ст л", "стл", "ст ложка", "ст ложки", "столовая ложка", "столовые ложки",
        "столовых ложек", "столовой ложки", "столовую ложку", "ст ложку",
        "tbsp", "tablespoon", "tablespoons",
    ),
    "ч. л.": (
        "ч л", "чл", "ч ложка", "ч ложки", "чайная ложка", "чайные ложки", "чайных ложек",
        "чайной ложки", "чайную ложку", "ч ложку", "tsp", "teaspoon", "teaspoons",
    ),
    "стакан": ("стакан", "стакана", "стаканов", "cup", "cups"),
    "щепотка": ("щепотка", "щепотки", "щепоток", "pinch", "pinches"),
    "зубчик": ("зубчик", "зубчика", "зубчиков", "clove", "cloves"),
    "пучок": ("пучок", "пучка", "пучков", "bunch", "bunches"),
}  # fmt: skip
_UNITS = {synonym: unit for unit, synonyms in _UNIT_SYNONYMS.items() for synonym in synonyms}


def normalize_unit(raw: str | None) -> str | None:
    """One spelling per unit: "Гр." -> "г", "столовые ложки" -> "ст. л.", "tsp" -> "ч. л.".

    Unknown units ("банка") are kept as given.
    """
    if raw is None:
        return None
    key = " ".join(re.sub(r"[.,]", " ", raw.lower()).split())
    if not key:
        return None
    return _UNITS.get(key, raw.strip())


@dataclass(frozen=True)
class Ingredient:
    name: str
    amount: float | None = None
    unit: str | None = None
    # "по вкусу", "для жарки", "комнатной температуры"
    note: str | None = None

    def __post_init__(self) -> None:
        name = " ".join(self.name.split())
        if not name:
            raise InvalidRecipeError("У ингредиента нет названия")
        if self.amount is not None and self.amount <= 0:
            raise InvalidRecipeError(f"Неверное количество у «{name}»: {self.amount}")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unit", normalize_unit(self.unit))
        object.__setattr__(self, "note", (self.note or "").strip() or None)


@dataclass(frozen=True)
class RecipeSource:
    url: str
    platform: Platform
    video_id: str
    author: str | None = None

    @property
    def key(self) -> str:
        """One video, however the link was written: youtu.be/x and youtube.com/watch?v=x."""
        return f"{self.platform}:{self.video_id}"


@dataclass(frozen=True)
class Recipe:
    title: str
    ingredients: tuple[Ingredient, ...]
    steps: tuple[str, ...]
    source: RecipeSource
    servings: int | None = None
    total_minutes: int | None = None
    cuisine: str | None = None
    tags: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        title = " ".join(self.title.split())
        if not title:
            raise InvalidRecipeError("У рецепта нет названия")
        if not self.ingredients:
            raise InvalidRecipeError(f"В рецепте «{title}» нет ингредиентов")
        if self.servings is not None and self.servings <= 0:
            raise InvalidRecipeError(f"Неверное число порций: {self.servings}")
        if self.total_minutes is not None and self.total_minutes <= 0:
            raise InvalidRecipeError(f"Неверное время приготовления: {self.total_minutes}")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "steps", tuple(s.strip() for s in self.steps if s.strip()))
        tags = dict.fromkeys(t.strip().lower() for t in self.tags if t.strip())
        object.__setattr__(self, "tags", tuple(tags))


def new_recipe_id() -> str:
    """Short enough to type in the CLI or a bot command: "a3f9c2e1b7"."""
    return secrets.token_hex(5)


@dataclass(frozen=True)
class SavedRecipe:
    """A recipe kept in the collection, with the text it was extracted from."""

    id: str
    recipe: Recipe
    saved_at: datetime
    # Kept to re-extract the recipe later with a better prompt or model.
    source_text: SourceText
