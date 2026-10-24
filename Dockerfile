FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.12.15-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Not root: files written to the mounted ./data belong to the host user (UID 1000 is the
# first user on most Linux machines). Another UID: build with --build-arg APP_UID=$(id -u).
ARG APP_UID=1000
RUN useradd --create-home --uid ${APP_UID} app

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first: this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY src ./src
COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# The app user may write next to the code: pytest's cache, yt-dlp and deno caches live in $HOME.
RUN chown app /app
USER app

EXPOSE 8000

# One worker on purpose: import statuses, chats and the import limit live in the process.
CMD ["uvicorn", "receipt.bootstrap.api:create_api", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
