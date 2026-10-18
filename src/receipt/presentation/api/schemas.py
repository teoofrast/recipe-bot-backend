"""Request and response bodies of the API. Mapped from application DTOs, never passed inward."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from receipt.domain.import_job import ImportJob, ImportStatus
from receipt.domain.recipe import SavedRecipe


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ImportRequest(BaseModel):
    url: Annotated[
        str, Field(min_length=8, max_length=2000, examples=["https://youtu.be/QPy2sA8HC5U"])
    ]


class ImportJobResponse(BaseModel):
    id: str
    url: str
    status: ImportStatus
    recipe_id: str | None
    already_saved: bool
    error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: ImportJob) -> "ImportJobResponse":
        return cls(
            id=job.id,
            url=job.url,
            status=job.status,
            recipe_id=job.recipe_id,
            already_saved=job.already_saved,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class IngredientResponse(BaseModel):
    name: str
    amount: float | None
    unit: str | None
    note: str | None


class SourceResponse(BaseModel):
    url: str
    platform: str
    video_id: str
    author: str | None


class RecipeSummary(BaseModel):
    id: str
    title: str
    platform: str
    url: str
    total_minutes: int | None
    tags: list[str]
    saved_at: datetime

    @classmethod
    def of(cls, saved: SavedRecipe) -> "RecipeSummary":
        recipe = saved.recipe
        return cls(
            id=saved.id,
            title=recipe.title,
            platform=recipe.source.platform.value,
            url=recipe.source.url,
            total_minutes=recipe.total_minutes,
            tags=list(recipe.tags),
            saved_at=saved.saved_at,
        )


class RecipeResponse(BaseModel):
    id: str
    title: str
    servings: int | None
    total_minutes: int | None
    cuisine: str | None
    tags: list[str]
    ingredients: list[IngredientResponse]
    steps: list[str]
    source: SourceResponse
    saved_at: datetime

    @classmethod
    def of(cls, saved: SavedRecipe) -> "RecipeResponse":
        recipe, source = saved.recipe, saved.recipe.source
        return cls(
            id=saved.id,
            title=recipe.title,
            servings=recipe.servings,
            total_minutes=recipe.total_minutes,
            cuisine=recipe.cuisine,
            tags=list(recipe.tags),
            ingredients=[
                IngredientResponse(name=i.name, amount=i.amount, unit=i.unit, note=i.note)
                for i in recipe.ingredients
            ],
            steps=list(recipe.steps),
            source=SourceResponse(
                url=source.url,
                platform=source.platform.value,
                video_id=source.video_id,
                author=source.author,
            ),
            saved_at=saved.saved_at,
        )


class SearchHit(BaseModel):
    score: float
    recipe: RecipeSummary


class ReindexResponse(BaseModel):
    indexed: int


class ChatRequest(BaseModel):
    chat_id: Annotated[str, Field(min_length=1, max_length=100, examples=["web-3f2a"])]
    text: Annotated[
        str, Field(min_length=1, max_length=4000, examples=["Что приготовить из курицы?"])
    ]


class SourceRecipeResponse(BaseModel):
    recipe_id: str
    title: str
    url: str


class ChatResponse(BaseModel):
    text: str
    sources: list[SourceRecipeResponse]
    model: str | None


# SSE events of POST /chat/stream: the "event" field names the type, "data" is one of these.


class TokenData(BaseModel):
    event: Literal["token"] = "token"
    text: str


class ToolData(BaseModel):
    event: Literal["tool"] = "tool"
    name: str
    description: str


class SourcesData(BaseModel):
    event: Literal["sources"] = "sources"
    recipes: list[SourceRecipeResponse]


class DoneData(BaseModel):
    event: Literal["done"] = "done"
    model: str | None


class ErrorData(BaseModel):
    event: Literal["error"] = "error"
    message: str


type ChatStreamEvent = TokenData | ToolData | SourcesData | DoneData | ErrorData
