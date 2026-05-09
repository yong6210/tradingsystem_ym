from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_runtime_scripts_support_direct_help_from_other_cwd(tmp_path: Path) -> None:
    for script in (
        ROOT_DIR / "scripts" / "run_micro_live_preflight.py",
        ROOT_DIR / "scripts" / "run_runtime_signoff_review.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()
