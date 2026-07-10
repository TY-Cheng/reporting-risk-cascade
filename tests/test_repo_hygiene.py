from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def test_uv_lock_is_tracked_and_only_public_lake_shell_is_executable() -> None:
    required_files = {
        "uv.lock",
        ".python-version",
        "scripts/run_public_lake_full.sh",
    }
    assert all((REPO_ROOT / relative).is_file() for relative in required_files)
    assert (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"

    if not (REPO_ROOT / ".git").exists():
        return

    tracked = set(_git("ls-files").splitlines())
    assert "uv.lock" in tracked
    assert ".python-version" in tracked

    executable = {
        line.split("\t", maxsplit=1)[1]
        for line in _git("ls-files", "-s").splitlines()
        if line.startswith("100755 ")
    }
    assert executable == {"scripts/run_public_lake_full.sh"}
