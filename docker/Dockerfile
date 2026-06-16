# Applicant API image. python:3.11-slim + uv.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# Install uv (the project toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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
