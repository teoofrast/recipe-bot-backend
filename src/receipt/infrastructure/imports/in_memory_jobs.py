from receipt.domain.import_job import ImportJob

# Statuses are watched for minutes, not kept forever: old finished jobs are dropped.
MAX_JOBS = 500


class InMemoryImportJobRepository:
    """Import statuses in memory: lost on restart, which is fine for progress reports.

    Works because the API runs as one process (one uvicorn worker).
    """

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: dict[str, ImportJob] = {}
        self._max_jobs = max_jobs

    async def add(self, job: ImportJob) -> None:
        self._jobs[job.id] = job
        self._forget_old()

    async def get(self, job_id: str) -> ImportJob | None:
        return self._jobs.get(job_id)

    async def update(self, job: ImportJob) -> None:
        self._jobs[job.id] = job

    def _forget_old(self) -> None:
        finished = sorted(
            (job for job in self._jobs.values() if job.is_finished), key=lambda job: job.updated_at
        )
        for job in finished[: max(0, len(self._jobs) - self._max_jobs)]:
            del self._jobs[job.id]
