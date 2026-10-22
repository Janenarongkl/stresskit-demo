"""Smoke-test the SDK wheel in a clean venv.  Usage: python scripts/check_sdk_wheel.py DIST_DIR

Checks that the wheel installs, imports, reports the same version as sdk/pyproject.toml, and
does not pull in the server's dependencies.
"""

import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

wheels = sorted(Path(sys.argv[1]).glob("stresskit_sdk-*.whl"))
if len(wheels) != 1:
    sys.exit(f"expected one SDK wheel in {sys.argv[1]}, found {len(wheels)}")
version = tomllib.loads((ROOT / "sdk" / "pyproject.toml").read_text())["project"]["version"]

with tempfile.TemporaryDirectory() as tmp:
    venv.create(tmp, with_pip=True)
    py = str(Path(tmp) / ("Scripts" if sys.platform == "win32" else "bin") / "python")
    subprocess.run([py, "-m", "pip", "install", "-q", str(wheels[0])], check=True)
    check = (
        "import importlib.util as u, stresskit_sdk as s; "
        f"assert s.__version__ == {version!r}, s.__version__; "
        "extra = [n for n in ('fastapi', 'pydantic', 'jwt') if u.find_spec(n)]; "
        "assert not extra, f'server dependencies installed: {extra}'"
    )
    subprocess.run([py, "-c", check], check=True)
print(f"{wheels[0].name}: installs cleanly, version {version}, client-only dependencies")
