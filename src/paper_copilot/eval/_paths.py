"""Resolve project-local default paths for eval artifacts.

Goldens and run records live in ``<repo>/eval/`` and are committed to
git. When the CLI is installed via ``uv tool install``, ``__file__``
points into the venv, so the old ``Path(__file__).parents[3]`` trick
resolved to ``.../python3.12/`` instead of the project — silently
writing artifacts into the venv. Resolve from cwd instead.
"""

from __future__ import annotations

from pathlib import Path


def find_project_root() -> Path:
    """Walk up from cwd looking for ``.git/`` or ``pyproject.toml``; fall back to cwd."""
    start = Path.cwd().resolve()
    for d in (start, *start.parents):
        if (d / ".git").exists() or (d / "pyproject.toml").exists():
            return d
    return start


def default_goldens_dir() -> Path:
    return find_project_root() / "eval" / "goldens"


def default_runs_dir() -> Path:
    return find_project_root() / "eval" / "runs"
