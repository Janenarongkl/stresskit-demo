import importlib.util
import json
from pathlib import Path

from stresskit_api import models

ROOT = Path(__file__).resolve().parents[1]


def shape(spec: dict) -> dict:
    """The parts of the contract we own: routes, status codes, schema fields and required fields.

    Compared instead of the full JSON because FastAPI and Pydantic versions render small
    details (titles, ordering, nullable forms) differently.
    """
    routes = {
        f"{method.upper()} {path}": sorted(op.get("responses", {}))
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
    }
    schemas = {
        name: {"fields": sorted(s.get("properties", {})), "required": sorted(s.get("required", []))}
        for name, s in spec["components"]["schemas"].items()
        if "properties" in s and hasattr(models, name)  # skip FastAPI's own schemas
    }
    return {"routes": routes, "schemas": schemas}


def test_committed_contract_matches_code():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "scripts/export_openapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text())
    current = json.loads(module.render())
    assert shape(committed) == shape(current), "Run: python scripts/export_openapi.py"
