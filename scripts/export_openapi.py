"""Write the API contract to docs/openapi.json.  Usage: python scripts/export_openapi.py

CI runs tests/test_openapi.py, which fails if the committed file is out of date, so the
contract in the repo always matches the code.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stresskit_api import create_app  # noqa: E402

OUT = ROOT / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2) + "\n"


if __name__ == "__main__":
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
