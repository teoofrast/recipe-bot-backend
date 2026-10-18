import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from receipt.domain.errors import DomainError


class ImportStatus(StrEnum):
    QUEUED = "queued"  # waiting for a free import slot
    READING = "reading"  # title, description, subtitles
    TRANSCRIBING = "transcribing"  # speech, when the text was not enough
    WATCHING = "watching"  # frames, when the method is only shown, not told
    EXTRACTING = "extracting"  # the LLM reads the recipe out of the text
    SAVING = "saving"
    DONE = "done"  # the recipe is in the collection (new or saved before)
    NO_RECIPE = "no_recipe"  # the video has no recipe: a normal outcome, not a failure
    FAILED = "failed"


FINAL_STATUSES = frozenset({ImportStatus.DONE, ImportStatus.NO_RECIPE, ImportStatus.FAILED})


class ImportJobFinishedError(DomainError):
    """A finished import cannot change any more."""


def new_import_job_id() -> str:
    return secrets.token_hex(6)


@dataclass(frozen=True)
class ImportJob:
    """One video link being turned into a saved recipe; its status is what users watch."""

    id: str
    url: str
    status: ImportStatus
    created_at: datetime
    updated_at: datetime
    recipe_id: str | None = None
    # True when the video's recipe was already in the collection and nothing was added.
    already_saved: bool = False
    error: str | None = None

    @classmethod
    def queued(cls, url: str, now: datetime) -> "ImportJob":
        return cls(
            id=new_import_job_id(),
            url=url,
            status=ImportStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )

    @property
    def is_finished(self) -> bool:
        return self.status in FINAL_STATUSES

    def advance(self, status: ImportStatus, now: datetime) -> "ImportJob":
        """Moves to the next stage; final outcomes go through done/no_recipe/fail."""
        if status in FINAL_STATUSES:
            raise ValueError(f"{status} is a final status: use done(), no_recipe() or fail()")
        return self._change(status=status, updated_at=now)

    def done(self, recipe_id: str, already_saved: bool, now: datetime) -> "ImportJob":
        return self._change(
            status=ImportStatus.DONE,
            recipe_id=recipe_id,
            already_saved=already_saved,
            updated_at=now,
        )

    def no_recipe(self, now: datetime) -> "ImportJob":
        return self._change(status=ImportStatus.NO_RECIPE, updated_at=now)

    def fail(self, error: str, now: datetime) -> "ImportJob":
        return self._change(status=ImportStatus.FAILED, error=error, updated_at=now)

    def _change(self, **changes: object) -> "ImportJob":
        if self.is_finished:
            raise ImportJobFinishedError(f"Импорт {self.id} уже завершён: {self.status}")
        return replace(self, **changes)  # type: ignore[arg-type]
