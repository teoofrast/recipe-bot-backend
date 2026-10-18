"""Saved recipes as JSON files: data/recipes/<id>.json, one file per recipe.

Readable by a person and by `git diff`, and enough for a personal collection: every lookup
reads the folder. The search index (card 7) is rebuilt from these files.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from receipt.application.errors import DuplicateRecipeError
from receipt.domain.recipe import Ingredient, Recipe, RecipeSource, SavedRecipe
from receipt.domain.source_text import SourceText
from receipt.domain.video import Platform

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
# Ids come from users (API, bot): anything else must never become a path.
_ID = re.compile(r"[0-9a-f]{1,32}")


class JsonFileRecipeRepository:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        # Check-then-write of add() and delete() must not interleave.
        self._lock = asyncio.Lock()

    async def add(self, saved: SavedRecipe) -> None:
        async with self._lock:
            if await self.get_by_source(saved.recipe.source.key):
                raise DuplicateRecipeError(saved.recipe.source.key)
            await asyncio.to_thread(self._write, saved)

    async def get(self, recipe_id: str) -> SavedRecipe | None:
        path = self._path(recipe_id)
        if path is None:
            return None
        return await asyncio.to_thread(self._read, path)

    async def get_by_source(self, source_key: str) -> SavedRecipe | None:
        recipes = await self.list_all()
        return next((saved for saved in recipes if saved.recipe.source.key == source_key), None)

    async def list_all(self) -> list[SavedRecipe]:
        saved = await asyncio.to_thread(self._read_all)
        return sorted(saved, key=lambda item: item.saved_at, reverse=True)

    async def delete(self, recipe_id: str) -> bool:
        path = self._path(recipe_id)
        if path is None:
            return False
        async with self._lock:
            try:
                await asyncio.to_thread(path.unlink)
            except FileNotFoundError:
                return False
        return True

    def _path(self, recipe_id: str) -> Path | None:
        if not _ID.fullmatch(recipe_id):
            return None
        return self._directory / f"{recipe_id}.json"

    def _write(self, saved: SavedRecipe) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{saved.id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(to_document(saved), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        # Atomic on the same file system: a crash leaves the old file or the new one, never half.
        os.replace(temporary, path)

    def _read(self, path: Path) -> SavedRecipe | None:
        try:
            return from_document(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as error:
            logger.error("Unreadable recipe file %s: %s", path, error)
            return None

    def _read_all(self) -> list[SavedRecipe]:
        if not self._directory.is_dir():
            return []
        found = (self._read(path) for path in self._directory.glob("*.json"))
        return [saved for saved in found if saved is not None]


def to_document(saved: SavedRecipe) -> dict[str, Any]:
    recipe, source, text = saved.recipe, saved.recipe.source, saved.source_text
    return {
        "format": FORMAT_VERSION,
        "id": saved.id,
        "saved_at": saved.saved_at.isoformat(),
        "recipe": {
            "title": recipe.title,
            "servings": recipe.servings,
            "total_minutes": recipe.total_minutes,
            "cuisine": recipe.cuisine,
            "tags": list(recipe.tags),
            "ingredients": [
                {"name": item.name, "amount": item.amount, "unit": item.unit, "note": item.note}
                for item in recipe.ingredients
            ],
            "steps": list(recipe.steps),
        },
        "source": {
            "url": source.url,
            "platform": source.platform.value,
            "video_id": source.video_id,
            "author": source.author,
        },
        "source_text": {
            "title": text.title,
            "description": text.description,
            "subtitles": text.subtitles,
            "transcript": text.transcript,
            "frames": text.frames,
        },
    }


def from_document(document: dict[str, Any]) -> SavedRecipe:
    if document.get("format") != FORMAT_VERSION:
        raise ValueError(f"unknown format {document.get('format')!r}")
    recipe, source, text = document["recipe"], document["source"], document["source_text"]
    return SavedRecipe(
        id=document["id"],
        saved_at=datetime.fromisoformat(document["saved_at"]),
        recipe=Recipe(
            title=recipe["title"],
            servings=recipe["servings"],
            total_minutes=recipe["total_minutes"],
            cuisine=recipe["cuisine"],
            tags=tuple(recipe["tags"]),
            ingredients=tuple(Ingredient(**item) for item in recipe["ingredients"]),
            steps=tuple(recipe["steps"]),
            source=RecipeSource(
                url=source["url"],
                platform=Platform(source["platform"]),
                video_id=source["video_id"],
                author=source["author"],
            ),
        ),
        source_text=SourceText(**text),
    )
