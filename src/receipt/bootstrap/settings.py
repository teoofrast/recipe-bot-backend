from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Lists are written in the environment as comma-separated values: STT_MODELS=a,b,c
type CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """App configuration from environment variables (and .env for local runs)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Saved recipes and other local data; mounted into the container as /app/data.
    data_dir: Path = Path("data")

    # Netscape-format cookies for platforms that require login (usually Instagram).
    ytdlp_cookies_file: Path | None = None

    # Subtitle languages to try after the video's own language, in order.
    subtitle_languages: CommaList = ["ru", "en"]

    openrouter_api_key: SecretStr | None = None
    # Speech-to-text models on OpenRouter, tried in order. gpt-4o-mini-transcribe returns
    # nothing for music without speech, where Whisper makes up "subtitles by ..." lines.
    stt_models: CommaList = ["openai/gpt-4o-mini-transcribe", "openai/whisper-large-v3-turbo"]

    # Free chat models on OpenRouter, tried in order. Picked by a real probe (Russian recipe
    # text): extraction needs JSON by schema, chat needs tool calling. Free models come and
    # go and hit shared rate limits often, hence several of each.
    llm_extract_models: CommaList = [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "dots-studio/dots-3-note-preview:free",
    ]
    llm_chat_models: CommaList = [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "poolside/laguna-s-2.1:free",
        "google/gemma-4-31b-it:free",
    ]
    # Hard limit per model call, then the next model is tried. Free models write a recipe's
    # JSON slowly (60-70 s for 20 ingredients), and the import runs in the background; a chat
    # answer is awaited by a person.
    llm_extract_timeout_seconds: float = 120
    llm_chat_timeout_seconds: float = 40

    @field_validator(
        "subtitle_languages", "stt_models", "llm_extract_models", "llm_chat_models", mode="before"
    )
    @classmethod
    def _split_commas(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            # An empty variable (e.g. "LLM_CHAT_MODELS=" copied from .env.example) means
            # "not set", not "no models at all".
            assert info.field_name is not None
            return items or cls.model_fields[info.field_name].get_default(call_default_factory=True)
        return value

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, value: object) -> object:
        return value or None
