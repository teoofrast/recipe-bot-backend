"""Search index in Chroma: one document per recipe, vectors from OpenRouter embeddings."""

from collections.abc import Sequence
from typing import Any, Protocol

import chromadb
import httpx
from chromadb.api import AsyncClientAPI
from chromadb.api.models.AsyncCollection import AsyncCollection
from chromadb.errors import ChromaError, NotFoundError

from receipt.application.errors import SearchUnavailableError
from receipt.application.ports.recipe_index import RecipeFilters, RecipeHit
from receipt.domain.recipe import Recipe, SavedRecipe

COLLECTION = "recipes"
# Recipes per embeddings request when indexing many.
EMBEDDING_BATCH = 64
# Tag filters run after the vector search, so ask for more candidates than will be returned.
TAG_FILTER_OVERFETCH = 4


class Embeddings(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


def recipe_document(recipe: Recipe) -> str:
    """What the recipe is about, as text for the embedding: dish, ingredients, how it is made."""
    ingredients = ", ".join(item.name for item in recipe.ingredients)
    parts = [
        recipe.title,
        f"Кухня: {recipe.cuisine}" if recipe.cuisine else "",
        f"Теги: {', '.join(recipe.tags)}" if recipe.tags else "",
        f"Ингредиенты: {ingredients}",
        " ".join(recipe.steps),
    ]
    return "\n".join(part for part in parts if part)


def recipe_metadata(recipe: Recipe) -> dict[str, Any]:
    # Chroma metadata values are scalars and cannot be None: absent means unknown.
    metadata: dict[str, Any] = {"platform": recipe.source.platform.value, "title": recipe.title}
    if recipe.total_minutes is not None:
        metadata["total_minutes"] = recipe.total_minutes
    if recipe.cuisine:
        metadata["cuisine"] = recipe.cuisine
    if recipe.tags:
        metadata["tags"] = "|" + "|".join(recipe.tags) + "|"
    return metadata


def where_clause(filters: RecipeFilters) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = []
    if filters.max_minutes is not None:
        # Recipes with unknown time have no "total_minutes" and do not pass: "quick" needs proof.
        conditions.append({"total_minutes": {"$lte": filters.max_minutes}})
    if filters.cuisine:
        conditions.append({"cuisine": {"$eq": filters.cuisine.strip().lower()}})
    if filters.platform:
        conditions.append({"platform": {"$eq": filters.platform.value}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def has_tags(metadata: dict[str, Any] | None, tags: tuple[str, ...]) -> bool:
    stored = str((metadata or {}).get("tags", ""))
    return all(f"|{tag.strip().lower()}|" in stored for tag in tags)


def to_hits(
    ids: Sequence[str],
    distances: Sequence[float],
    metadatas: Sequence[dict[str, Any]],
    tags: tuple[str, ...],
    min_score: float,
    limit: int,
) -> list[RecipeHit]:
    hits = []
    for recipe_id, distance, metadata in zip(ids, distances, metadatas, strict=True):
        # Cosine distance is 0..2; similarity 1 - distance is 1 for the same meaning.
        score = round(1 - distance, 4)
        if score >= min_score and has_tags(metadata, tags):
            hits.append(RecipeHit(recipe_id=recipe_id, score=score))
    return hits[:limit]


class ChromaRecipeIndex:
    def __init__(
        self,
        host: str,
        port: int,
        embeddings: Embeddings,
        collection: str = COLLECTION,
        min_score: float = 0.0,
    ) -> None:
        self._host = host
        self._port = port
        self._embeddings = embeddings
        self._collection_name = collection
        self._min_score = min_score
        self._client: AsyncClientAPI | None = None

    async def index(self, saved: SavedRecipe) -> None:
        await self.index_many([saved])

    async def index_many(self, recipes: Sequence[SavedRecipe]) -> None:
        collection = await self._collection()
        for start in range(0, len(recipes), EMBEDDING_BATCH):
            batch = recipes[start : start + EMBEDDING_BATCH]
            documents = [recipe_document(saved.recipe) for saved in batch]
            vectors = await self._embeddings.embed_documents(documents)
            await self._call(
                collection.upsert(
                    ids=[saved.id for saved in batch],
                    embeddings=vectors,  # type: ignore[arg-type]
                    documents=documents,
                    metadatas=[recipe_metadata(saved.recipe) for saved in batch],
                )
            )

    async def remove(self, recipe_id: str) -> None:
        collection = await self._collection()
        await self._call(collection.delete(ids=[recipe_id]))

    async def clear(self) -> None:
        client = await self._connect()
        try:
            await self._call(client.delete_collection(self._collection_name))
        except SearchUnavailableError as error:
            if not isinstance(error.__cause__, NotFoundError):
                raise
            # No collection yet: already clear.

    async def search(self, text: str, filters: RecipeFilters, limit: int) -> list[RecipeHit]:
        vector = await self._embeddings.embed_query(text)
        collection = await self._collection()
        count = await self._call(collection.count())
        if count == 0:
            return []
        wanted = limit * TAG_FILTER_OVERFETCH if filters.tags else limit
        result = await self._call(
            collection.query(
                query_embeddings=[vector],
                n_results=min(wanted, count),
                where=where_clause(filters),
                include=["distances", "metadatas"],
            )
        )
        return to_hits(
            ids=result["ids"][0],
            distances=(result["distances"] or [[]])[0],
            metadatas=[dict(item or {}) for item in (result["metadatas"] or [[]])[0]],
            tags=filters.tags,
            min_score=self._min_score,
            limit=limit,
        )

    async def _connect(self) -> AsyncClientAPI:
        if self._client is None:
            try:
                self._client = await chromadb.AsyncHttpClient(host=self._host, port=self._port)
            except (httpx.HTTPError, ChromaError) as error:
                raise SearchUnavailableError(
                    f"Chroma недоступна ({self._host}:{self._port}): {error}"
                ) from error
        return self._client

    async def _collection(self) -> AsyncCollection:
        client = await self._connect()
        return await self._call(
            client.get_or_create_collection(
                self._collection_name,
                configuration={"hnsw": {"space": "cosine"}},
                # Vectors come from OpenRouter, not from a model inside Chroma.
                embedding_function=None,
            )
        )

    async def _call(self, awaitable: Any) -> Any:
        try:
            return await awaitable
        except (httpx.HTTPError, ChromaError) as error:
            # Server down (httpx) or refusing the request (Chroma): both mean no search now.
            raise SearchUnavailableError(f"Chroma недоступна: {error}") from error
