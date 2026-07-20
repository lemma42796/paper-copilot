"""Resolve project-local default paths for eval artifacts.

Goldens and run records live in ``<repo>/eval/`` and are committed to
git. Resolve from cwd so installed-package paths do not redirect
artifacts into a virtual environment.
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


def default_report_path() -> Path:
    return find_project_root() / "eval" / "report.html"
