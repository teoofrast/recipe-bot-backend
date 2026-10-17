import pytest

from receipt.bootstrap.settings import Settings


def test_lists_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBTITLE_LANGUAGES", " de , en ")
    monkeypatch.setenv("LLM_CHAT_MODELS", "a/b:free,c/d:free")

    settings = Settings(_env_file=None)

    assert settings.subtitle_languages == ["de", "en"]
    assert settings.llm_chat_models == ["a/b:free", "c/d:free"]


def test_empty_variables_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_EXTRACT_MODELS", "LLM_CHAT_MODELS", "STT_MODELS", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(name, "")

    settings = Settings(_env_file=None)
    defaults = Settings.model_fields

    assert settings.llm_extract_models == defaults["llm_extract_models"].default
    assert settings.llm_chat_models == defaults["llm_chat_models"].default
    assert settings.stt_models == defaults["stt_models"].default
    assert settings.openrouter_api_key is None
