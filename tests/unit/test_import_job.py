from datetime import UTC, datetime, timedelta

import pytest

from receipt.domain.import_job import ImportJob, ImportJobFinishedError, ImportStatus
from receipt.infrastructure.imports.in_memory_jobs import InMemoryImportJobRepository

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_a_job_goes_through_stages_to_done() -> None:
    job = ImportJob.queued(" https://youtu.be/x ".strip(), T0)
    assert (job.status, job.is_finished, len(job.id)) == (ImportStatus.QUEUED, False, 12)

    job = job.advance(ImportStatus.READING, T0 + timedelta(seconds=1))
    job = job.advance(ImportStatus.EXTRACTING, T0 + timedelta(seconds=2))
    job = job.done("abc", already_saved=False, now=T0 + timedelta(seconds=3))

    assert job.status is ImportStatus.DONE
    assert job.recipe_id == "abc"
    assert job.is_finished
    assert job.updated_at == T0 + timedelta(seconds=3)
    assert job.created_at == T0


def test_a_finished_job_does_not_change() -> None:
    for finished in (
        ImportJob.queued("u", T0).no_recipe(T0),
        ImportJob.queued("u", T0).fail("boom", T0),
        ImportJob.queued("u", T0).done("abc", already_saved=True, now=T0),
    ):
        with pytest.raises(ImportJobFinishedError):
            finished.advance(ImportStatus.READING, T0)
        with pytest.raises(ImportJobFinishedError):
            finished.fail("again", T0)


def test_final_statuses_are_set_only_through_their_methods() -> None:
    with pytest.raises(ValueError, match="final"):
        ImportJob.queued("u", T0).advance(ImportStatus.DONE, T0)


async def test_in_memory_jobs_forget_old_finished_ones() -> None:
    jobs = InMemoryImportJobRepository(max_jobs=2)
    old = ImportJob.queued("u1", T0).fail("x", T0)
    running = ImportJob.queued("u2", T0)
    await jobs.add(old)
    await jobs.add(running)

    newest = ImportJob.queued("u3", T0 + timedelta(minutes=1))
    await jobs.add(newest)

    assert await jobs.get(old.id) is None
    assert await jobs.get(running.id) == running  # unfinished ones are never dropped
    assert await jobs.get(newest.id) == newest
