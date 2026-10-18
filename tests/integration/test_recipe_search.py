"""Real search: Chroma from docker-compose (localhost:8001) + OpenRouter embeddings.

Run explicitly: ``docker compose up -d chroma && uv run pytest -m integration -k search``.
Works in a throwaway collection, never in the real "recipes" one.
"""

import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import chromadb
import pytest

from receipt.application.ports.recipe_index import RecipeFilters
from receipt.application.recipes.search import (
    ReindexRecipes,
    ReindexRecipesHandler,
    SearchRecipes,
    SearchRecipesHandler,
)
from receipt.bootstrap.settings import Settings
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource, SavedRecipe
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform
from receipt.infrastructure.recipes.json_repository import JsonFileRecipeRepository
from receipt.infrastructure.search.chroma_index import ChromaRecipeIndex
from receipt.infrastructure.search.embeddings import OpenRouterEmbeddings

SETTINGS = Settings()
API_KEY = SETTINGS.openrouter_api_key.get_secret_value() if SETTINGS.openrouter_api_key else None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(API_KEY is None, reason="OPENROUTER_API_KEY is not set"),
]

# (id, title, ingredients, minutes, tags); ids are hex, like real ones (the repository checks)
RECIPES = [
    ("c1", "Курица карри", ("куриное филе", "кокосовое молоко", "карри", "рис"), 40, ("ужин",)),
    ("c2", "Цезарь с курицей", ("куриная грудка", "салат романо", "пармезан"), 20, ("салат",)),
    ("a1", "Сырники", ("творог", "яйцо", "мука", "сахар"), 25, ("завтрак",)),
    ("b1", "Борщ", ("говядина", "свёкла", "капуста", "картофель"), 120, ("суп", "обед")),
    ("e1", "Паста карбонара", ("спагетти", "бекон", "желтки", "пармезан"), 25, ("ужин",)),
    ("f1", "Овощное рагу", ("кабачок", "баклажан", "перец", "помидоры"), 45, ("без мяса",)),
    ("d1", "Брауни", ("шоколад", "сливочное масло", "сахар", "яйца"), 50, ("десерт",)),
]


def saved(
    recipe_id: str, title: str, ingredients: tuple[str, ...], minutes: int, tags: tuple[str, ...]
) -> SavedRecipe:
    return SavedRecipe(
        id=recipe_id,
        saved_at=datetime(2026, 1, 1, tzinfo=UTC),
        recipe=Recipe(
            title=title,
            ingredients=tuple(Ingredient(name) for name in ingredients),
            steps=(),
            source=RecipeSource(
                url=f"https://youtu.be/{recipe_id}", platform=Platform.YOUTUBE, video_id=recipe_id
            ),
            total_minutes=minutes,
            tags=tags,
        ),
        source_text=SourceText(title=title, description=""),
    )


@pytest.fixture
async def setup(
    tmp_path: Path,
) -> AsyncIterator[tuple[ChromaRecipeIndex, JsonFileRecipeRepository]]:
    try:
        client = await chromadb.AsyncHttpClient(
            host=SETTINGS.chroma_host, port=SETTINGS.chroma_port
        )
        await client.heartbeat()
    except Exception:
        pytest.skip(f"Chroma is not running on {SETTINGS.chroma_host}:{SETTINGS.chroma_port}")
    collection = f"recipes_test_{secrets.token_hex(4)}"
    index = ChromaRecipeIndex(
        host=SETTINGS.chroma_host,
        port=SETTINGS.chroma_port,
        embeddings=OpenRouterEmbeddings(api_key=API_KEY, model=SETTINGS.embedding_model),
        collection=collection,
    )
    repository = JsonFileRecipeRepository(tmp_path / "recipes")
    for row in RECIPES:
        await repository.add(saved(*row))
    await ReindexRecipesHandler(index, repository).handle(ReindexRecipes())
    yield index, repository
    await client.delete_collection(collection)


async def search(
    index: ChromaRecipeIndex, repository: JsonFileRecipeRepository, text: str, **filters: object
) -> list[str]:
    handler = SearchRecipesHandler(index, repository)
    found = await handler.handle(
        SearchRecipes(text=text, filters=RecipeFilters(**filters), limit=3)
    )  # type: ignore[arg-type]
    return [item.saved.recipe.title for item in found]


async def test_what_to_cook_with_chicken(
    setup: tuple[ChromaRecipeIndex, JsonFileRecipeRepository],
) -> None:
    titles = await search(*setup, "что приготовить из курицы")

    assert set(titles[:2]) == {"Курица карри", "Цезарь с курицей"}


async def test_filters_by_time_and_tags(
    setup: tuple[ChromaRecipeIndex, JsonFileRecipeRepository],
) -> None:
    assert (await search(*setup, "что приготовить из курицы", max_minutes=30))[
        0
    ] == "Цезарь с курицей"
    assert await search(*setup, "что-нибудь на ужин", tags=("ужин",)) in (
        ["Курица карри", "Паста карбонара"],
        ["Паста карбонара", "Курица карри"],
    )


async def test_removed_recipe_is_not_found(
    setup: tuple[ChromaRecipeIndex, JsonFileRecipeRepository],
) -> None:
    index, repository = setup

    await index.remove("a1")

    assert "Сырники" not in await search(index, repository, "сырники из творога")


async def test_reindex_restores_a_lost_index(
    setup: tuple[ChromaRecipeIndex, JsonFileRecipeRepository],
) -> None:
    index, repository = setup
    await index.clear()
    assert await search(index, repository, "борщ со свёклой") == []

    count = await ReindexRecipesHandler(index, repository).handle(ReindexRecipes())

    assert count == len(RECIPES)
    assert (await search(index, repository, "борщ со свёклой"))[0] == "Борщ"
