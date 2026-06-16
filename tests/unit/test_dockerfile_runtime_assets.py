"""Guard: the Docker image must contain every repo-relative path the app loads at
runtime (FR-INSTALL-3). Tests run from the repo root where these dirs always exist,
so a missing `COPY` in the Dockerfile would pass tests yet crash in the container —
exactly the class of bug this asserts against.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO / "docker" / "Dockerfile"

# Top-level repo dirs/files resolved at runtime via Path(__file__).parents[3|4]/...
# (see static.py, latex_tailor.py, moderncv_converter.py, update.py).
_REQUIRED_IN_IMAGE = ["src", "frontend", "templates", "scripts", "alembic.ini"]


def test_dockerfile_copies_all_runtime_assets():
    text = _DOCKERFILE.read_text()
    copied = " ".join(
        line for line in text.splitlines() if line.strip().startswith("COPY")
    )
    for asset in _REQUIRED_IN_IMAGE:
        assert re.search(rf"\b{re.escape(asset)}\b", copied), (
            f"Dockerfile must COPY '{asset}' — the app loads it at runtime, so a "
            f"missing COPY passes tests (repo root) but crashes in the image."
        )


def test_runtime_template_dir_exists():
    # The render engines resolve parents[4]/templates/latex/moderncv/main.tex.j2.
    assert (_REPO / "templates" / "latex" / "moderncv" / "main.tex.j2").is_file()
