"""SK-20: the SDK's version is declared once per place and the two agree."""

import tomllib
from pathlib import Path

import stresskit_sdk

ROOT = Path(__file__).resolve().parents[1]


def test_sdk_version_matches_its_package_metadata():
    meta = tomllib.loads((ROOT / "sdk" / "pyproject.toml").read_text())["project"]
    assert meta["version"] == stresskit_sdk.__version__
    assert meta["dependencies"] == ["httpx>=0.27"]
