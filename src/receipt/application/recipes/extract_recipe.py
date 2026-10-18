import logging
from dataclasses import dataclass, replace

from receipt.application.cqrs import Query
from receipt.application.errors import ApplicationError
from receipt.application.mediator import Mediator
from receipt.application.ports.recipe_extractor import RecipeExtractor
from receipt.application.video.get_video_frames import GetVideoFrames
from receipt.application.video.get_video_text import GetVideoText
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.application.video.subtitles import language_base
from receipt.domain.recipe import (
    Recipe,
    RecipeSource,
    fuller,
    lacks_method,
    speech_may_complete,
)
from receipt.domain.source_text import SourceText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecipeDraft:
    """What was extracted from a video, before anything is saved."""

    recipe: Recipe | None
    text: SourceText


@dataclass(frozen=True)
class ExtractRecipe(Query[RecipeDraft]):
    """Recipe from a video link: text of the video, speech if needed, then the LLM."""

    url: str


class ExtractRecipeHandler:
    def __init__(self, mediator: Mediator, extractor: RecipeExtractor) -> None:
        self._mediator = mediator
        self._extractor = extractor

    async def handle(self, request: ExtractRecipe) -> RecipeDraft:
        """The same order as the import graph: text, then speech, then frames, as needed."""
        video_text = await self._mediator.send(GetVideoText(url=request.url))
        video, text = video_text.video, video_text.text
        source = RecipeSource(
            url=video.url, platform=video.platform, video_id=video.video_id, author=video.author
        )
        language = language_base(video.language) if video.language else None
        transcribed = text.needs_transcription
        if transcribed:
            text = await self._with_speech(text, video.url, language)
        recipe = await self._extractor.extract(text, source)

        if not transcribed and speech_may_complete(text, recipe):
            text = await self._with_speech(text, video.url, language)
            recipe = fuller(recipe, await self._extractor.extract(text, source))
        if lacks_method(recipe):
            try:
                frames = await self._mediator.send(GetVideoFrames(url=video.url))
            except ApplicationError as error:
                # The frames are a last resort: without them the recipe is what it is.
                logger.warning("Frames of %s were not described: %s", video.url, error)
            else:
                text = replace(text, frames=frames.text)
                recipe = fuller(recipe, await self._extractor.extract(text, source))
        return RecipeDraft(recipe=recipe, text=text)

    async def _with_speech(self, text: SourceText, url: str, language: str | None) -> SourceText:
        transcript = await self._mediator.send(GetVideoTranscript(url=url, language=language))
        return replace(text, transcript=transcript.text)
