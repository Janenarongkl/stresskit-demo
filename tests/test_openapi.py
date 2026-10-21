import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_committed_contract_matches_code():
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "scripts/export_openapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (ROOT / "docs" / "openapi.json").read_text()
    assert committed == module.render(), "Run: python scripts/export_openapi.py"
