"""Writes the OpenAPI schema to a file (default: openapi.json) for frontend type generation."""

import json
import sys
from pathlib import Path

from receipt.application.mediator import Mediator
from receipt.bootstrap.container import build_container
from receipt.presentation.api.app import create_app


def schema() -> dict[str, object]:
    # The schema does not depend on the key, and CI has no real one.
    return create_app(build_container().resolve(Mediator), api_key="openapi-export").openapi()


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    target.write_text(json.dumps(schema(), ensure_ascii=False, indent=2) + "\n")
    print(f"OpenAPI schema written to {target}")


if __name__ == "__main__":
    main()
