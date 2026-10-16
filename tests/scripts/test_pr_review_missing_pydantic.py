"""pr_review.py names a missing pydantic in one line instead of a traceback."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DRIVER = (
    "import runpy, sys; sys.modules['pydantic'] = None; "
    "runpy.run_path(sys.argv[1], run_name='__main__')"
)


def test_missing_pydantic_is_one_line_and_exit_2(plugin_root: Path) -> None:
    script = plugin_root / "scripts" / "pr_review.py"
    done = subprocess.run(
        [sys.executable, "-c", DRIVER, str(script), "--help"], capture_output=True, text=True
    )
    assert done.returncode == 2, done.stderr
    assert "Traceback" not in done.stderr
    lines = [ln for ln in done.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, done.stderr
    assert "pydantic" in lines[0]
