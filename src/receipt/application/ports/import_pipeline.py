from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from receipt.domain.import_job import ImportStatus

# Called when the pipeline enters a stage: READING, TRANSCRIBING, EXTRACTING, SAVING.
type StageCallback = Callable[[ImportStatus], Awaitable[None]]


class OutcomeKind(StrEnum):
    SAVED = "saved"
    ALREADY_SAVED = "already_saved"
    NO_RECIPE = "no_recipe"


@dataclass(frozen=True)
class ImportOutcome:
    kind: OutcomeKind
    recipe_id: str | None = None


class RecipeImportPipeline(Protocol):
    """Video link -> saved recipe: text, speech if needed, extraction, saving.

    Raises DomainError / ApplicationError subclasses for expected failures.
    """

    async def run(self, url: str, on_stage: StageCallback) -> ImportOutcome: ...
