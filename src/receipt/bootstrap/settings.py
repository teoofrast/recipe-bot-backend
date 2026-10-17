from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration from environment variables (and .env for local runs)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
