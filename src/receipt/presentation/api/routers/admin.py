from fastapi import APIRouter

from receipt.application.recipes.search import ReindexRecipes
from receipt.presentation.api.dependencies import MediatorDep
from receipt.presentation.api.schemas import ErrorResponse, ReindexResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reindex", responses={503: {"model": ErrorResponse}})
async def reindex(mediator: MediatorDep) -> ReindexResponse:
    """Пересобрать поисковый индекс из сохранённых рецептов."""
    return ReindexResponse(indexed=await mediator.send(ReindexRecipes()))
