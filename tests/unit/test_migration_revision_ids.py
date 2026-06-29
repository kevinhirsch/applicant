"""Alembic revision IDs must fit the ``alembic_version.version_num`` column.

Alembic creates ``alembic_version.version_num`` as ``VARCHAR(32)`` by default, so a
revision identifier longer than 32 chars makes ``alembic upgrade`` crash on a real
database with ``StringDataRightTruncation`` — even though ``alembic heads`` and the
in-memory test lane (which never runs a real upgrade) stay green. CI therefore
never caught ``0006_generated_material_provenance`` (34 chars), which broke a real
deploy. This pins the whole revision set to <=32 chars so the class is caught here.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src/applicant/adapters/storage/alembic/versions"
)
_REVISION_RE = re.compile(r"^revision = ['\"]([^'\"]+)['\"]", re.MULTILINE)
#: Alembic's default ``alembic_version.version_num`` column width.
_ALEMBIC_VERSION_NUM_MAX = 32


def test_all_revision_ids_fit_alembic_version_column():
    files = sorted(VERSIONS_DIR.glob("[0-9]*.py"))
    assert files, f"no migration files found under {VERSIONS_DIR}"
    offenders = {}
    for f in files:
        match = _REVISION_RE.search(f.read_text())
        assert match, f"no `revision = ...` line in {f.name}"
        rid = match.group(1)
        if len(rid) > _ALEMBIC_VERSION_NUM_MAX:
            offenders[f.name] = (rid, len(rid))
    assert not offenders, (
        "revision id(s) exceed alembic_version.version_num VARCHAR(32) and will "
        f"crash `alembic upgrade` on a real database: {offenders}"
    )
