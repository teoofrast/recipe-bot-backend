"""The import as a LangGraph graph: each step is a node, the flow and retries are edges."""

from dataclasses import replace
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from receipt.application.errors import (
    LlmUnavailableError,
    VideoUnavailableError,
    VideoUnavailableReason,
)
from receipt.application.mediator import Mediator
from receipt.application.ports.import_pipeline import ImportOutcome, OutcomeKind, StageCallback
from receipt.application.ports.recipe_extractor import RecipeExtractor
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.application.ports.video_downloader import VideoMetadata
from receipt.application.recipes.collection import SaveRecipe
from receipt.application.video.get_video_text import GetVideoText
from receipt.application.video.get_video_transcript import GetVideoTranscript
from receipt.application.video.subtitles import language_base
from receipt.domain.import_job import ImportStatus
from receipt.domain.recipe import Recipe, RecipeSource, speech_may_complete
from receipt.domain.source_text import SourceText


class ImportState(TypedDict, total=False):
    url: str
    video: VideoMetadata
    text: SourceText
    recipe: Recipe | None
    # The speech was recognized (even if the video turned out silent): not again.
    transcribed: bool
    outcome: ImportOutcome


def is_transient(error: Exception) -> bool:
    """Worth another try: the platform did not answer, not "private" or "removed"."""
    return isinstance(error, VideoUnavailableError) and (
        error.reason is VideoUnavailableReason.UNKNOWN
    )


NETWORK_RETRY = RetryPolicy(max_attempts=3, initial_interval=2.0, retry_on=is_transient)
# Every free model hit its limit (20 requests/min): wait and go through them once more.
LLM_RETRY = RetryPolicy(max_attempts=2, initial_interval=15.0, retry_on=LlmUnavailableError)


def source_of(video: VideoMetadata) -> RecipeSource:
    return RecipeSource(
        url=video.url, platform=video.platform, video_id=video.video_id, author=video.author
    )


def fuller(before: Recipe | None, after: Recipe | None) -> Recipe | None:
    """After the speech, the model may still miss the method (free models vary from run to run):
    the caption's recipe is kept unless the new one has more steps."""
    if before is None or (after is not None and len(after.steps) >= len(before.steps)):
        return after or before
    return before


class LangGraphImportPipeline:
    """read_video → check_saved → [transcribe] → extract → [transcribe → extract] → save.

    Steps reuse the application's own use cases through the mediator (so they are logged and
    behave as everywhere else); the graph adds the order, the branches and the retries.
    """

    def __init__(
        self, mediator: Mediator, extractor: RecipeExtractor, repository: RecipeRepository
    ) -> None:
        self._mediator = mediator
        self._extractor = extractor
        self._repository = repository
        self._graph = self._build()

    async def run(self, url: str, on_stage: StageCallback) -> ImportOutcome:
        state = await self._graph.ainvoke(
            {"url": url}, config={"configurable": {"on_stage": on_stage}}
        )
        return state["outcome"]

    def mermaid(self) -> str:
        return self._graph.get_graph().draw_mermaid()

    def _build(self) -> Any:
        graph = StateGraph(ImportState)
        graph.add_node("read_video", self._read_video, retry_policy=NETWORK_RETRY)
        graph.add_node("check_saved", self._check_saved)
        graph.add_node("transcribe", self._transcribe, retry_policy=NETWORK_RETRY)
        graph.add_node("extract", self._extract, retry_policy=LLM_RETRY)
        graph.add_node("save", self._save)
        graph.add_node("no_recipe", self._no_recipe)

        graph.add_edge(START, "read_video")
        graph.add_edge("read_video", "check_saved")
        graph.add_conditional_edges(
            "check_saved",
            self._after_check,
            {"done": END, "transcribe": "transcribe", "extract": "extract"},
        )
        graph.add_edge("transcribe", "extract")
        graph.add_conditional_edges(
            "extract",
            self._after_extract,
            {"transcribe": "transcribe", "no_recipe": "no_recipe", "save": "save"},
        )
        graph.add_edge("save", END)
        graph.add_edge("no_recipe", END)
        return graph.compile()

    # Nodes

    async def _read_video(self, state: ImportState, config: RunnableConfig) -> ImportState:
        await _stage(config, ImportStatus.READING)
        result = await self._mediator.send(GetVideoText(url=state["url"]))
        return {"video": result.video, "text": result.text}

    async def _check_saved(self, state: ImportState) -> ImportState:
        # Before any LLM call: a video saved earlier costs nothing the second time.
        existing = await self._repository.get_by_source(source_of(state["video"]).key)
        if existing is None:
            return {}
        return {"outcome": ImportOutcome(OutcomeKind.ALREADY_SAVED, existing.id)}

    async def _transcribe(self, state: ImportState, config: RunnableConfig) -> ImportState:
        await _stage(config, ImportStatus.TRANSCRIBING)
        video = state["video"]
        language = language_base(video.language) if video.language else None
        transcript = await self._mediator.send(GetVideoTranscript(url=video.url, language=language))
        return {"text": replace(state["text"], transcript=transcript.text), "transcribed": True}

    async def _extract(self, state: ImportState, config: RunnableConfig) -> ImportState:
        await _stage(config, ImportStatus.EXTRACTING)
        recipe = await self._extractor.extract(state["text"], source_of(state["video"]))
        return {"recipe": fuller(state.get("recipe"), recipe)}

    async def _save(self, state: ImportState, config: RunnableConfig) -> ImportState:
        await _stage(config, ImportStatus.SAVING)
        recipe = state["recipe"]
        assert recipe is not None  # _after_extract sends only a found recipe here
        result = await self._mediator.send(SaveRecipe(recipe=recipe, source_text=state["text"]))
        kind = OutcomeKind.SAVED if result.created else OutcomeKind.ALREADY_SAVED
        return {"outcome": ImportOutcome(kind, result.saved.id)}

    @staticmethod
    async def _no_recipe(state: ImportState) -> ImportState:
        return {"outcome": ImportOutcome(OutcomeKind.NO_RECIPE)}

    # Edges

    @staticmethod
    def _after_check(state: ImportState) -> str:
        if "outcome" in state:
            return "done"
        return "transcribe" if state["text"].needs_transcription else "extract"

    @staticmethod
    def _after_extract(state: ImportState) -> str:
        recipe = state.get("recipe")
        # The caption listed ingredients only: the method is in the voice-over.
        if not state.get("transcribed") and speech_may_complete(state["text"], recipe):
            return "transcribe"
        return "save" if recipe is not None else "no_recipe"


async def _stage(config: RunnableConfig, status: ImportStatus) -> None:
    on_stage: StageCallback = config["configurable"]["on_stage"]
    await on_stage(status)
