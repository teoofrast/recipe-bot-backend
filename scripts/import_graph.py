"""Prints the import graph as Mermaid (paste into README or https://mermaid.live)."""

from receipt.application.ports.import_pipeline import RecipeImportPipeline
from receipt.bootstrap.container import build_container
from receipt.infrastructure.imports.langgraph_pipeline import LangGraphImportPipeline


def main() -> None:
    container = build_container()
    pipeline = container.resolve(RecipeImportPipeline)
    assert isinstance(pipeline, LangGraphImportPipeline)
    print(pipeline.mermaid())


if __name__ == "__main__":
    main()
