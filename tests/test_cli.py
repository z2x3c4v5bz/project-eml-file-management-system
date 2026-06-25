import subprocess
import sys
from pathlib import Path


def test_main_module_runs_as_script():
    repo_root = Path(__file__).resolve().parents[1]
    # __main__.py uses relative imports so it must be invoked via -m, not directly.
    result = subprocess.run(
        [sys.executable, "-m", "eml_manager", "version"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "eml-manager" in result.stdout
