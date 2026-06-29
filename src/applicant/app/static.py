"""StaticFiles mount helper (mirrors the Applicant serving pattern) (FR-UI-1).

Serves ``workspace/static`` (the workspace front-door shell + our screens under
``workspace/static/``) at ``/static``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def static_dir(configured: str) -> Path:
    """Resolve the static directory to an absolute path (repo-root relative)."""
    p = Path(configured)
    if p.is_absolute():
        return p
    # repo root = three parents up from this file (src/applicant/app/static.py).
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / configured


def mount_static(app: FastAPI, configured_dir: str) -> None:
    """Mount the static directory at /static if it exists."""
    directory = static_dir(configured_dir)
    if directory.is_dir():
        app.mount("/static", StaticFiles(directory=str(directory)), name="static")
