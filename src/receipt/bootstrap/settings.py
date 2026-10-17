from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Lists are written in the environment as comma-separated values: STT_MODELS=a,b,c
type CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """App configuration from environment variables (and .env for local runs)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Netscape-format cookies for platforms that require login (usually Instagram).
    ytdlp_cookies_file: Path | None = None

    # Subtitle languages to try after the video's own language, in order.
    subtitle_languages: CommaList = ["ru", "en"]

    openrouter_api_key: SecretStr | None = None
    # Speech-to-text models on OpenRouter, tried in order.
    stt_models: CommaList = ["openai/whisper-large-v3-turbo", "openai/whisper-large-v3"]

    @field_validator("subtitle_languages", "stt_models", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, value: object) -> object:
        return value or None
