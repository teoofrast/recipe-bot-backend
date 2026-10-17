"""Writes the OpenAPI schema to a file (default: openapi.json) for frontend type generation."""

import json
import sys
from pathlib import Path

from receipt.bootstrap.api import create_api


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    target.write_text(json.dumps(create_api().openapi(), ensure_ascii=False, indent=2) + "\n")
    print(f"OpenAPI schema written to {target}")


if __name__ == "__main__":
    main()
