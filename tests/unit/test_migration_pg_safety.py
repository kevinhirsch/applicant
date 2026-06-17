"""Guard: Alembic migrations must not use jsonb-only operators on the portable
JSON ``payload`` column (FR-CRIT-4 / prod-Postgres safety).

``pending_actions.payload`` (and other JSON columns) are a portable ``json`` type,
not ``jsonb``. The jsonb key-exists operator ``?`` raises on Postgres
("operator does not exist: json ? unknown") — a prod-only failure the SQLite test
lane never sees. This pins migrations to json-safe extraction (``->>`` + IS NOT
NULL) so a deploy migration can't break again the way 0004 did.
"""

from __future__ import annotations

import re
from pathlib import Path

_VERSIONS = (
    Path(__file__).resolve().parents[2]
    / "src" / "applicant" / "adapters" / "storage" / "alembic" / "versions"
)

# The jsonb-only key-exists operator applied to a column (e.g. ``payload ? 'k'``),
# ignoring the ``?`` used as a SQL bind placeholder.
_JSONB_KEY_EXISTS = re.compile(r"\b\w+\s+\?\s*['\"]")


def _sql_lines(path: Path) -> list[str]:
    # Only inspect lines that look like SQL inside op.execute(...) strings.
    return [
        ln
        for ln in path.read_text().splitlines()
        if ("UPDATE " in ln or "SELECT " in ln or "WHERE " in ln) and "#" not in ln.split('"')[0]
    ]


def test_no_jsonb_key_exists_operator_in_migrations():
    offenders: list[str] = []
    for mig in sorted(_VERSIONS.glob("[0-9]*.py")):
        for ln in _sql_lines(mig):
            if _JSONB_KEY_EXISTS.search(ln):
                offenders.append(f"{mig.name}: {ln.strip()}")
    assert not offenders, (
        "Migrations use the jsonb-only `?` key-exists operator on a JSON column "
        "(fails on Postgres). Use `col->>'key' IS NOT NULL` instead:\n"
        + "\n".join(offenders)
    )
