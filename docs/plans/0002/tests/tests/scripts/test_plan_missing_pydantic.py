"""plan.py names a missing pydantic in one ``problem:`` line and exits 1, no traceback."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DRIVER = (
    "import runpy, sys; sys.modules[sys.argv[1]] = None; sys.argv = sys.argv[2:]; "
    "runpy.run_path(sys.argv[0], run_name='__main__')"
)


def test_missing_pydantic_is_one_problem_line_and_exit_1(plugin_root: Path) -> None:
    script = plugin_root / "scripts" / "plan.py"
    done = subprocess.run(
        [sys.executable, "-c", DRIVER, "pydantic", str(script), "--help"], capture_output=True, text=True
    )
    assert done.returncode == 1, done.stderr
    assert "Traceback" not in done.stderr
    lines = [ln for ln in done.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, done.stderr
    assert lines[0].startswith("problem:") and "pydantic>=2" in lines[0]
