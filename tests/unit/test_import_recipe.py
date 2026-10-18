import asyncio

import pytest

from receipt.application.errors import (
    ImportJobNotFoundError,
    VideoUnavailableError,
    VideoUnavailableReason,
)
from receipt.application.ports.import_pipeline import ImportOutcome, OutcomeKind, StageCallback
from receipt.application.recipes.import_recipe import (
    CreateImportJob,
    CreateImportJobHandler,
    GetImportStatus,
    GetImportStatusHandler,
    ImportLimiter,
    ImportRecipe,
    ImportRecipeHandler,
)
from receipt.domain.import_job import ImportStatus
from receipt.domain.video import UnsupportedUrlError
from receipt.infrastructure.imports.in_memory_jobs import InMemoryImportJobRepository
from tests.conftest import FIXED_NOW
from tests.fakes import FakeClock

URL = "https://youtu.be/abc123"
SAVED = ImportOutcome(OutcomeKind.SAVED, "r1")


class ScriptedPipeline:
    """Goes through ``stages``, then returns ``outcome`` or raises ``error``."""

    def __init__(
        self,
        outcome: ImportOutcome = SAVED,
        stages: tuple[ImportStatus, ...] = (ImportStatus.READING, ImportStatus.EXTRACTING),
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.outcome, self.stages, self.error, self.delay = outcome, stages, error, delay
        self.active = 0
        self.max_active = 0

    async def run(self, url: str, on_stage: StageCallback) -> ImportOutcome:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            for stage in self.stages:
                await on_stage(stage)
                await asyncio.sleep(self.delay)
            if self.error is not None:
                raise self.error
            return self.outcome
        finally:
            self.active -= 1


class RecordingJobs(InMemoryImportJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.history: list[ImportStatus] = []

    async def update(self, job) -> None:  # type: ignore[no-untyped-def]
        self.history.append(job.status)
        await super().update(job)


def handler(
    pipeline: ScriptedPipeline, jobs: InMemoryImportJobRepository, limit: int = 2
) -> ImportRecipeHandler:
    return ImportRecipeHandler(pipeline, jobs, ImportLimiter(limit), FakeClock(FIXED_NOW))


async def test_import_reports_every_stage_and_ends_done() -> None:
    jobs = RecordingJobs()

    job = await handler(ScriptedPipeline(), jobs).handle(ImportRecipe(url=URL))

    assert job.status is ImportStatus.DONE
    assert (job.recipe_id, job.already_saved) == ("r1", False)
    assert jobs.history == [ImportStatus.READING, ImportStatus.EXTRACTING, ImportStatus.DONE]
    assert await jobs.get(job.id) == job


@pytest.mark.parametrize(
    ("outcome", "status", "already_saved"),
    [
        (ImportOutcome(OutcomeKind.ALREADY_SAVED, "r0"), ImportStatus.DONE, True),
        (ImportOutcome(OutcomeKind.NO_RECIPE), ImportStatus.NO_RECIPE, False),
    ],
)
async def test_outcomes(outcome: ImportOutcome, status: ImportStatus, already_saved: bool) -> None:
    job = await handler(ScriptedPipeline(outcome), InMemoryImportJobRepository()).handle(
        ImportRecipe(url=URL)
    )

    assert job.status is status
    assert job.already_saved is already_saved


async def test_expected_failures_end_up_in_the_job() -> None:
    error = VideoUnavailableError(VideoUnavailableReason.PRIVATE, "Private video")

    job = await handler(ScriptedPipeline(error=error), InMemoryImportJobRepository()).handle(
        ImportRecipe(url=URL)
    )

    assert job.status is ImportStatus.FAILED
    assert job.error == "Не удалось получить видео: видео приватное"


async def test_crashes_end_up_in_the_job_without_details(caplog: pytest.LogCaptureFixture) -> None:
    job = await handler(
        ScriptedPipeline(error=KeyError("video")), InMemoryImportJobRepository()
    ).handle(ImportRecipe(url=URL))

    assert job.status is ImportStatus.FAILED
    assert job.error == "Внутренняя ошибка при импорте"
    assert "crashed" in caplog.text  # the traceback is in the log


async def test_import_of_a_created_job_and_its_status() -> None:
    jobs = InMemoryImportJobRepository()
    clock = FakeClock(FIXED_NOW)
    created = await CreateImportJobHandler(jobs, clock).handle(CreateImportJob(url=URL))
    assert created.status is ImportStatus.QUEUED

    await handler(ScriptedPipeline(), jobs).handle(ImportRecipe(url=URL, job_id=created.id))

    status = await GetImportStatusHandler(jobs).handle(GetImportStatus(job_id=created.id))
    assert status.status is ImportStatus.DONE


async def test_unknown_jobs_and_unsupported_links() -> None:
    jobs = InMemoryImportJobRepository()
    with pytest.raises(ImportJobNotFoundError):
        await GetImportStatusHandler(jobs).handle(GetImportStatus(job_id="nope"))
    with pytest.raises(ImportJobNotFoundError):
        await handler(ScriptedPipeline(), jobs).handle(ImportRecipe(url=URL, job_id="nope"))
    with pytest.raises(UnsupportedUrlError):
        await CreateImportJobHandler(jobs, FakeClock(FIXED_NOW)).handle(
            CreateImportJob(url="https://vimeo.com/1")
        )


async def test_three_imports_at_once_run_two_at_a_time_and_all_finish() -> None:
    pipeline = ScriptedPipeline(delay=0.05)
    jobs = InMemoryImportJobRepository()
    imports = handler(pipeline, jobs, limit=2)

    results = await asyncio.gather(
        *(imports.handle(ImportRecipe(url=f"{URL}{n}")) for n in range(3))
    )

    assert [job.status for job in results] == [ImportStatus.DONE] * 3
    assert pipeline.max_active == 2
