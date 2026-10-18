from collections.abc import Sequence

import openai

from receipt.application.errors import SearchUnavailableError

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Picked by a probe on Russian recipes: 7/7 queries found the right recipe first, including
# an English query against Russian recipes (bge-m3: 6/7). About $0.01 per million tokens.
DEFAULT_MODEL = "intfloat/multilingual-e5-large"


class OpenRouterEmbeddings:
    """Text -> vector through OpenRouter's OpenAI-compatible /embeddings.

    E5 models were trained with "query: " and "passage: " prefixes and need them to compare
    a short question with a long recipe well.
    """

    def __init__(
        self,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        *,
        base_url: str = OPENROUTER_URL,
        timeout_seconds: float = 30,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._prefixes = ("query: ", "passage: ") if "e5" in model else ("", "")
        self._client = client or (
            openai.AsyncOpenAI(
                api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=2
            )
            if api_key
            else None
        )

    async def embed_query(self, text: str) -> list[float]:
        [vector] = await self._embed([self._prefixes[0] + text])
        return vector

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed([self._prefixes[1] + text for text in texts])

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            raise SearchUnavailableError("Не задан OPENROUTER_API_KEY: поиск недоступен")
        try:
            response = await self._client.embeddings.create(model=self._model, input=texts)
        except openai.OpenAIError as error:
            raise SearchUnavailableError(f"Эмбеддинги недоступны: {error}") from error
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
