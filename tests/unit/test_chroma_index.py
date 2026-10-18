from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from receipt.application.errors import SearchUnavailableError
from receipt.application.ports.recipe_index import RecipeFilters, RecipeHit
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource
from receipt.domain.video import Platform
from receipt.infrastructure.search.chroma_index import (
    has_tags,
    recipe_document,
    recipe_metadata,
    to_hits,
    where_clause,
)
from receipt.infrastructure.search.embeddings import OpenRouterEmbeddings

RECIPE = Recipe(
    title="Сырники",
    ingredients=(Ingredient("творог", 400, "г"), Ingredient("яйцо", 1)),
    steps=("Смешайте", "Обжарьте"),
    source=RecipeSource(url="https://youtu.be/x", platform=Platform.YOUTUBE, video_id="x"),
    total_minutes=20,
    cuisine="русская",
    tags=("завтрак", "без мяса"),
)


def test_document_says_what_the_recipe_is_about() -> None:
    assert recipe_document(RECIPE) == (
        "Сырники\nКухня: русская\nТеги: завтрак, без мяса\n"
        "Ингредиенты: творог, яйцо\nСмешайте Обжарьте"
    )


def test_metadata_has_only_known_values() -> None:
    assert recipe_metadata(RECIPE) == {
        "platform": "youtube",
        "title": "Сырники",
        "total_minutes": 20,
        "cuisine": "русская",
        "tags": "|завтрак|без мяса|",
    }
    bare = Recipe(title="Борщ", ingredients=(Ingredient("свёкла"),), steps=(), source=RECIPE.source)
    assert recipe_metadata(bare) == {"platform": "youtube", "title": "Борщ"}


@pytest.mark.parametrize(
    ("filters", "where"),
    [
        (RecipeFilters(), None),
        (RecipeFilters(max_minutes=30), {"total_minutes": {"$lte": 30}}),
        (
            RecipeFilters(max_minutes=30, cuisine=" Русская ", platform=Platform.TIKTOK),
            {
                "$and": [
                    {"total_minutes": {"$lte": 30}},
                    {"cuisine": {"$eq": "русская"}},
                    {"platform": {"$eq": "tiktok"}},
                ]
            },
        ),
        # Tags are checked after the search, not in Chroma's where.
        (RecipeFilters(tags=("завтрак",)), None),
    ],
)
def test_where_clause(filters: RecipeFilters, where: dict[str, Any] | None) -> None:
    assert where_clause(filters) == where


def test_has_tags() -> None:
    metadata = recipe_metadata(RECIPE)

    assert has_tags(metadata, ())
    assert has_tags(metadata, ("завтрак", " Без мяса "))
    assert not has_tags(metadata, ("завтрак", "суп"))
    assert not has_tags(metadata, ("мяса",))  # whole tags only
    assert not has_tags(None, ("завтрак",))


class FakeEmbeddingsApi:
    def __init__(self, error: Exception | None = None) -> None:
        self.inputs: list[str] = []
        self.model = ""
        self.error = error

    async def create(self, model: str, input: list[str]) -> Any:
        if self.error:
            raise self.error
        self.model, self.inputs = model, input
        # Returned out of order on purpose: the order is restored by index.
        data = [SimpleNamespace(index=i, embedding=[float(i)]) for i in range(len(input))]
        return SimpleNamespace(data=list(reversed(data)))


def embeddings(model: str, api: FakeEmbeddingsApi) -> OpenRouterEmbeddings:
    return OpenRouterEmbeddings(
        api_key="sk-test",
        model=model,
        client=SimpleNamespace(embeddings=api),  # type: ignore[arg-type]
    )


async def test_e5_models_get_query_and_passage_prefixes() -> None:
    api = FakeEmbeddingsApi()
    e5 = embeddings("intfloat/multilingual-e5-large", api)

    assert await e5.embed_documents(["Сырники", "Борщ"]) == [[0.0], [1.0]]
    assert api.inputs == ["passage: Сырники", "passage: Борщ"]

    assert await e5.embed_query("из творога") == [0.0]
    assert api.inputs == ["query: из творога"]
    assert api.model == "intfloat/multilingual-e5-large"


async def test_other_models_get_no_prefixes() -> None:
    api = FakeEmbeddingsApi()

    await embeddings("baai/bge-m3", api).embed_query("из творога")

    assert api.inputs == ["из творога"]


async def test_embedding_errors_mean_search_is_unavailable() -> None:
    request = httpx.Request("POST", "https://openrouter.ai")
    api = FakeEmbeddingsApi(error=openai.APIConnectionError(request=request))

    with pytest.raises(SearchUnavailableError, match="Эмбеддинги"):
        await embeddings("intfloat/multilingual-e5-large", api).embed_query("x")


async def test_without_a_key_search_is_unavailable() -> None:
    with pytest.raises(SearchUnavailableError, match="OPENROUTER_API_KEY"):
        await OpenRouterEmbeddings(api_key=None).embed_query("x")


def test_hits_below_the_floor_or_without_the_tags_are_dropped() -> None:
    hits = to_hits(
        ids=["a", "b", "c", "d"],
        distances=[0.15, 0.18, 0.2, 0.3],
        metadatas=[
            {"tags": "|ужин|"},
            {"tags": "|завтрак|"},
            {"tags": "|ужин|"},
            {"tags": "|ужин|"},
        ],
        tags=("ужин",),
        min_score=0.78,
        limit=5,
    )

    assert hits == [RecipeHit("a", 0.85), RecipeHit("c", 0.8)]


def test_hits_are_cut_to_the_limit() -> None:
    hits = to_hits(
        ids=["a", "b", "c"], distances=[0.1, 0.2, 0.3], metadatas=[{}, {}, {}],
        tags=(), min_score=0, limit=2,
    )  # fmt: skip

    assert [hit.recipe_id for hit in hits] == ["a", "b"]
