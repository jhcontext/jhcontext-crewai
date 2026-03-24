"""Shared output directory for scenario runs.

``run.py`` sets ``current`` before launching flows.  Flows and
``validate.py`` import ``current`` to know where to write/read.
"""

from __future__ import annotations

from pathlib import Path

# Base directory for all runs
RUNS_DIR = Path(__file__).parent.parent / "output" / "runs"

# Active run directory — set by run.py before launching scenarios
current: Path = Path(__file__).parent.parent / "output"

# Symlink pointing to the latest run
LATEST_LINK = Path(__file__).parent.parent / "output" / "latest"


def next_run_dir() -> Path:
    """Create and return the next versioned run directory (v01, v02, ...)."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    existing = sorted(RUNS_DIR.glob("v[0-9][0-9]"))
    if existing:
        last_num = int(existing[-1].name[1:])
        next_num = last_num + 1
    else:
        next_num = 1

    run_dir = RUNS_DIR / f"v{next_num:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def set_current(run_dir: Path) -> None:
    """Set the active run directory and update the 'latest' symlink."""
    global current
    current = run_dir

    # Update latest symlink
    if LATEST_LINK.is_symlink() or LATEST_LINK.exists():
        LATEST_LINK.unlink()
    LATEST_LINK.symlink_to(run_dir.resolve())
