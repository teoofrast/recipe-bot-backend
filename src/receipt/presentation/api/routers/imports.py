import asyncio

from fastapi import APIRouter, status

from receipt.application.recipes.import_recipe import CreateImportJob, GetImportStatus, ImportRecipe
from receipt.presentation.api.dependencies import BackgroundTasksDep, MediatorDep
from receipt.presentation.api.schemas import ErrorResponse, ImportJobResponse, ImportRequest

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={422: {"model": ErrorResponse, "description": "Ссылка не поддерживается"}},
)
async def start_import(
    body: ImportRequest, mediator: MediatorDep, tasks: BackgroundTasksDep
) -> ImportJobResponse:
    """Принимает ссылку на видео; импорт идёт в фоне, статус — GET /imports/{id}."""
    job = await mediator.send(CreateImportJob(url=body.url))
    task = asyncio.create_task(mediator.send(ImportRecipe(url=job.url, job_id=job.id)))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return ImportJobResponse.of(job)


@router.get("/{job_id}", responses={404: {"model": ErrorResponse}})
async def get_import(job_id: str, mediator: MediatorDep) -> ImportJobResponse:
    """queued → reading → [transcribing] → extracting → saving → done | no_recipe | failed."""
    return ImportJobResponse.of(await mediator.send(GetImportStatus(job_id=job_id)))
