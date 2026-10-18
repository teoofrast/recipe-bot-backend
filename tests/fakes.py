from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from receipt.application.errors import (
    DuplicateRecipeError,
    VideoUnavailableError,
    VideoUnavailableReason,
)
from receipt.application.ports.recipe_index import RecipeFilters, RecipeHit
from receipt.application.ports.transcriber import Transcript
from receipt.application.ports.video_downloader import SubtitleTrack, VideoMetadata
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource, SavedRecipe
from receipt.domain.source_text import SourceText
from receipt.domain.video import detect_platform


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeVideoDownloader:
    """Answers every link with the same video; raises ``error`` instead, if set.

    Also plays SubtitleFetcher: ``subtitles`` maps a track language to its text, and
    ``subtitles_error`` is raised for every track if set.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        # Fail this many times with a transient "platform did not answer" before working.
        self.transient_failures = 0
        self.description = "Свёкла 2 шт, капуста 300 г"
        self.subtitle_tracks: tuple[SubtitleTrack, ...] = ()
        self.subtitles: dict[str, str] = {}
        self.subtitles_error: Exception | None = None

    async def fetch_metadata(self, url: str) -> VideoMetadata:
        platform = detect_platform(url)
        if self.error is not None:
            raise self.error
        if self.transient_failures:
            self.transient_failures -= 1
            raise VideoUnavailableError(VideoUnavailableReason.UNKNOWN, "connection reset")
        return VideoMetadata(
            url=url,
            platform=platform,
            video_id="abc123",
            title="Борщ за 30 минут",
            description=self.description,
            author="chef",
            duration_seconds=59,
            language="ru",
            subtitle_tracks=self.subtitle_tracks,
        )

    async def download_audio(self, url: str, target_dir: Path) -> Path:
        if self.error is not None:
            raise self.error
        path = target_dir / "abc123.m4a"
        path.write_bytes(b"fake audio")
        return path

    async def fetch_subtitle_text(self, track: SubtitleTrack) -> str:
        if self.subtitles_error is not None:
            raise self.subtitles_error
        return self.subtitles[track.language]


class FakeTranscriber:
    """Remembers what it was given; answers with ``text`` or raises ``error``."""

    def __init__(self) -> None:
        self.text = "Берём свёклу и капусту"
        self.error: Exception | None = None
        self.calls: list[tuple[Path, bool, str | None]] = []

    async def transcribe(self, audio_path: Path, language: str | None = None) -> Transcript:
        # Whether the file still exists at the moment of transcription.
        self.calls.append((audio_path, audio_path.exists(), language))
        if self.error is not None:
            raise self.error
        return Transcript(text=self.text, model="fake/whisper")


class FakeRecipeExtractor:
    """Finds a recipe in any text that mentions "свёкл"; remembers what it was given."""

    def __init__(self) -> None:
        self.calls: list[tuple[SourceText, RecipeSource]] = []

    async def extract(self, text: SourceText, source: RecipeSource) -> Recipe | None:
        self.calls.append((text, source))
        if "свёкл" not in text.combined().lower():
            return None
        return Recipe(
            title="Борщ",
            ingredients=(Ingredient("свёкла", 2, "шт"),),
            steps=("Сварите",),
            source=source,
        )


class InMemoryRecipeRepository:
    """RecipeRepository in a dict; passes the same contract tests as the JSON files."""

    def __init__(self) -> None:
        self.recipes: dict[str, SavedRecipe] = {}

    async def add(self, saved: SavedRecipe) -> None:
        if await self.get_by_source(saved.recipe.source.key):
            raise DuplicateRecipeError(saved.recipe.source.key)
        self.recipes[saved.id] = saved

    async def get(self, recipe_id: str) -> SavedRecipe | None:
        return self.recipes.get(recipe_id)

    async def get_by_source(self, source_key: str) -> SavedRecipe | None:
        return next(
            (saved for saved in self.recipes.values() if saved.recipe.source.key == source_key),
            None,
        )

    async def list_all(self) -> list[SavedRecipe]:
        return sorted(self.recipes.values(), key=lambda saved: saved.saved_at, reverse=True)

    async def delete(self, recipe_id: str) -> bool:
        return self.recipes.pop(recipe_id, None) is not None


class FakeRecipeIndex:
    """Search by shared words instead of meaning; ``error`` makes every call fail."""

    def __init__(self) -> None:
        self.documents: dict[str, SavedRecipe] = {}
        self.error: Exception | None = None
        self.cleared = 0

    async def index(self, saved: SavedRecipe) -> None:
        self._fail()
        self.documents[saved.id] = saved

    async def index_many(self, recipes: Sequence[SavedRecipe]) -> None:
        for saved in recipes:
            await self.index(saved)

    async def remove(self, recipe_id: str) -> None:
        self._fail()
        self.documents.pop(recipe_id, None)

    async def clear(self) -> None:
        self._fail()
        self.cleared += 1
        self.documents.clear()

    async def search(self, text: str, filters: RecipeFilters, limit: int) -> list[RecipeHit]:
        self._fail()
        words = set(text.lower().split())
        hits = []
        for recipe_id, saved in self.documents.items():
            recipe = saved.recipe
            if filters.max_minutes is not None and (
                recipe.total_minutes is None or recipe.total_minutes > filters.max_minutes
            ):
                continue
            if not set(filters.tags) <= set(recipe.tags):
                continue
            content = " ".join([recipe.title, *(item.name for item in recipe.ingredients)])
            shared = words & set(content.lower().split())
            if shared:
                hits.append(RecipeHit(recipe_id, score=len(shared) / len(words)))
        return sorted(hits, key=lambda hit: -hit.score)[:limit]

    def _fail(self) -> None:
        if self.error is not None:
            raise self.error
