"""Importing a recipe from a video link, with a status a person can watch."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from receipt.application.cqrs import Command, Query
from receipt.application.errors import ApplicationError, ImportJobNotFoundError
from receipt.application.ports.clock import Clock
from receipt.application.ports.import_jobs import ImportJobRepository
from receipt.application.ports.import_pipeline import (
    ImportOutcome,
    OutcomeKind,
    RecipeImportPipeline,
)
from receipt.domain.errors import DomainError
from receipt.domain.import_job import ImportJob, ImportStatus
from receipt.domain.video import detect_platform

logger = logging.getLogger(__name__)


class ImportLimiter:
    """At most N imports at once: each one downloads, transcribes and calls the LLM, and free
    models allow only 20 requests a minute. Others wait in the QUEUED status."""

    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._semaphore:
            yield


@dataclass(frozen=True)
class CreateImportJob(Command[ImportJob]):
    """Registers a link for import (QUEUED). The import itself is ImportRecipe, run apart."""

    url: str


class CreateImportJobHandler:
    def __init__(self, jobs: ImportJobRepository, clock: Clock) -> None:
        self._jobs = jobs
        self._clock = clock

    async def handle(self, request: CreateImportJob) -> ImportJob:
        detect_platform(request.url)  # an unsupported link fails now, not in the background
        job = ImportJob.queued(request.url.strip(), self._clock.now())
        await self._jobs.add(job)
        return job


@dataclass(frozen=True)
class ImportRecipe(Command[ImportJob]):
    """Runs the import to its end and returns the finished job. Expected failures do not
    raise: they end up in the job (FAILED with a message), because nobody may be waiting."""

    url: str
    # A job made by CreateImportJob; without it a new one is created.
    job_id: str | None = None


class ImportRecipeHandler:
    def __init__(
        self,
        pipeline: RecipeImportPipeline,
        jobs: ImportJobRepository,
        limiter: ImportLimiter,
        clock: Clock,
    ) -> None:
        self._pipeline = pipeline
        self._jobs = jobs
        self._limiter = limiter
        self._clock = clock

    async def handle(self, request: ImportRecipe) -> ImportJob:
        job = await self._job_for(request)

        async def on_stage(status: ImportStatus) -> None:
            nonlocal job
            job = job.advance(status, self._clock.now())
            await self._jobs.update(job)

        try:
            async with self._limiter.slot():
                outcome = await self._pipeline.run(job.url, on_stage)
            job = self._finish(job, outcome)
        except (DomainError, ApplicationError) as error:
            job = job.fail(str(error), self._clock.now())
        except Exception:
            logger.exception("Import %s of %s crashed", job.id, job.url)
            job = job.fail("Внутренняя ошибка при импорте", self._clock.now())
        await self._jobs.update(job)
        return job

    async def _job_for(self, request: ImportRecipe) -> ImportJob:
        if request.job_id is None:
            return await CreateImportJobHandler(self._jobs, self._clock).handle(
                CreateImportJob(url=request.url)
            )
        job = await self._jobs.get(request.job_id)
        if job is None:
            raise ImportJobNotFoundError(request.job_id)
        return job

    def _finish(self, job: ImportJob, outcome: ImportOutcome) -> ImportJob:
        now = self._clock.now()
        if outcome.kind is OutcomeKind.NO_RECIPE:
            return job.no_recipe(now)
        assert outcome.recipe_id is not None
        return job.done(
            outcome.recipe_id, already_saved=outcome.kind is OutcomeKind.ALREADY_SAVED, now=now
        )


@dataclass(frozen=True)
class GetImportStatus(Query[ImportJob]):
    job_id: str


class GetImportStatusHandler:
    def __init__(self, jobs: ImportJobRepository) -> None:
        self._jobs = jobs

    async def handle(self, request: GetImportStatus) -> ImportJob:
        job = await self._jobs.get(request.job_id)
        if job is None:
            raise ImportJobNotFoundError(request.job_id)
        return job
