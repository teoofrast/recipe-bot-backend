import logging

# HTTP clients log every request at INFO (Chroma alone makes 5-6 per search): only problems.
_QUIET = ("httpx", "httpx2", "httpcore", "chromadb", "openai")


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in _QUIET:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLevelName(level)))
