from typing import Protocol

from receipt.domain.import_job import ImportJob


class ImportJobRepository(Protocol):
    async def add(self, job: ImportJob) -> None: ...

    async def get(self, job_id: str) -> ImportJob | None: ...

    async def update(self, job: ImportJob) -> None: ...
