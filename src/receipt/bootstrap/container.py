"""Composition root: the only place that knows which adapter implements which port."""

from typing import Any

import punq

from receipt.application.behaviors import ErrorBehavior, LoggingBehavior
from receipt.application.mediator import Mediator
from receipt.application.ports.clock import Clock
from receipt.application.ports.recipe_extractor import RecipeExtractor
from receipt.application.ports.recipe_index import RecipeIndex
from receipt.application.ports.recipe_repository import RecipeRepository
from receipt.application.ports.transcriber import Transcriber
from receipt.application.ports.video_downloader import SubtitleFetcher, VideoDownloader
from receipt.application.recipes.collection import (
    DeleteRecipe,
    DeleteRecipeHandler,
    GetRecipe,
    GetRecipeHandler,
    ListRecipes,
    ListRecipesHandler,
    SaveRecipe,
    SaveRecipeHandler,
)
from receipt.application.recipes.extract_recipe import ExtractRecipe, ExtractRecipeHandler
from receipt.application.recipes.search import (
    ReindexRecipes,
    ReindexRecipesHandler,
    SearchRecipes,
    SearchRecipesHandler,
)
from receipt.application.system.ping import Ping, PingHandler, PingStream, PingStreamHandler
from receipt.application.video.get_video_info import GetVideoInfo, GetVideoInfoHandler
from receipt.application.video.get_video_text import (
    GetVideoText,
    GetVideoTextHandler,
    SubtitleLanguages,
)
from receipt.application.video.get_video_transcript import (
    GetVideoTranscript,
    GetVideoTranscriptHandler,
)
from receipt.bootstrap.settings import Settings
from receipt.infrastructure.clock import SystemClock
from receipt.infrastructure.llm.provider import ChatModelProvider, Purpose
from receipt.infrastructure.recipes.json_repository import JsonFileRecipeRepository
from receipt.infrastructure.recipes.llm_extractor import LlmRecipeExtractor
from receipt.infrastructure.search.chroma_index import ChromaRecipeIndex
from receipt.infrastructure.search.embeddings import OpenRouterEmbeddings
from receipt.infrastructure.transcription.openrouter import OpenRouterTranscriber
from receipt.infrastructure.video.yt_dlp_downloader import YtDlpVideoDownloader

HANDLERS: dict[type[Any], type[Any]] = {
    Ping: PingHandler,
    PingStream: PingStreamHandler,
    GetVideoInfo: GetVideoInfoHandler,
    GetVideoText: GetVideoTextHandler,
    GetVideoTranscript: GetVideoTranscriptHandler,
    ExtractRecipe: ExtractRecipeHandler,
    SaveRecipe: SaveRecipeHandler,
    GetRecipe: GetRecipeHandler,
    ListRecipes: ListRecipesHandler,
    DeleteRecipe: DeleteRecipeHandler,
    SearchRecipes: SearchRecipesHandler,
    ReindexRecipes: ReindexRecipesHandler,
}


def build_container(settings: Settings | None = None) -> punq.Container:
    """Builds the container. Re-registering a service afterwards overrides it (used by tests)."""
    settings = settings or Settings()
    container = punq.Container()
    container.register(Settings, instance=settings)

    # Ports -> adapters. Clients holding connections (LLM, Chroma) will be singletons too.
    container.register(Clock, SystemClock, scope=punq.Scope.singleton)
    yt_dlp_adapter = YtDlpVideoDownloader(cookies_file=settings.ytdlp_cookies_file)
    container.register(VideoDownloader, instance=yt_dlp_adapter)
    container.register(SubtitleFetcher, instance=yt_dlp_adapter)
    container.register(
        SubtitleLanguages, instance=SubtitleLanguages(tuple(settings.subtitle_languages))
    )
    api_key = (
        settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
    )
    container.register(
        Transcriber,
        instance=OpenRouterTranscriber(api_key=api_key, models=settings.stt_models),
    )
    # Used by the recipe extractor and the assistant (card 9).
    container.register(
        ChatModelProvider,
        instance=ChatModelProvider(
            api_key=api_key,
            models={
                Purpose.EXTRACT: settings.llm_extract_models,
                Purpose.CHAT: settings.llm_chat_models,
            },
            timeout_seconds={
                Purpose.EXTRACT: settings.llm_extract_timeout_seconds,
                Purpose.CHAT: settings.llm_chat_timeout_seconds,
            },
        ),
    )
    container.register(RecipeExtractor, LlmRecipeExtractor, scope=punq.Scope.singleton)
    # One instance: its lock is what keeps concurrent saves of one video from duplicating.
    container.register(
        RecipeRepository, instance=JsonFileRecipeRepository(settings.data_dir / "recipes")
    )
    container.register(
        RecipeIndex,
        instance=ChromaRecipeIndex(
            host=settings.chroma_host,
            port=settings.chroma_port,
            embeddings=OpenRouterEmbeddings(api_key=api_key, model=settings.embedding_model),
            min_score=settings.search_min_score,
        ),
    )

    # Handlers are transient: a fresh instance per request.
    for handler_type in HANDLERS.values():
        container.register(handler_type)

    container.register(
        Mediator,
        factory=lambda: Mediator(
            container.resolve,
            HANDLERS,
            behaviors=[LoggingBehavior(), ErrorBehavior()],
        ),
        scope=punq.Scope.singleton,
    )
    return container
