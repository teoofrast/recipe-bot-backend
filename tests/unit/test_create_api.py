import pytest

from receipt.bootstrap.api import MissingApiKeyError, create_api


@pytest.mark.parametrize("key", ["", "change-me"])
def test_the_api_does_not_start_without_a_real_key(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv("API_KEY", key)

    with pytest.raises(MissingApiKeyError, match="openssl rand -hex 32"):
        create_api()


def test_the_api_starts_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "a" * 64)

    assert create_api().title == "Recipe Bot API"
