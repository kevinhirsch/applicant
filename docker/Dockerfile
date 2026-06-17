# Applicant API image. python:3.11-slim + uv.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Install uv (the project toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System packages for the resume-render pipeline (FR-RESUME-3/4). The renderer
# auto-detects these via shutil.which() and silently degrades (no real PDF) when
# absent, so they must be in the image — both render paths are reachable depending
# on the user's onboarding accept/reject choice:
#   * LaTeX (primary): xelatex/lualatex + fontspec / moderncv / fontawesome5
#   * docx (fallback): LibreOffice headless (soffice --convert-to pdf)
# Targeted texlive subset (not texlive-full) to keep the image ~2GB instead of ~4GB.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        texlive-xetex \
        texlive-luatex \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        lmodern \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
RUN uv sync --no-dev --frozen || uv sync --no-dev

# App code + vendored frontend + LaTeX/docx templates (loaded at runtime as
# parents[4]/templates by the resume-render engines — must be in the image).
COPY alembic.ini ./
COPY frontend ./frontend
COPY templates ./templates
COPY scripts ./scripts

EXPOSE 8000

# Run the FastAPI app via uvicorn.
CMD ["uv", "run", "uvicorn", "applicant.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
