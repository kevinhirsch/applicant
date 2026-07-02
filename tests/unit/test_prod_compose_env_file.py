"""Prod compose feeds the repo-root ``.env`` to the engine container too.

Before the fix, only ``applicant-ui`` declared an ``env_file: [{path: ../.env,
required: false}]`` entry. The ``api`` (engine) service had none, so the ~50
engine vars documented in ``.env.example`` that aren't ALSO explicitly
interpolated in the service's ``environment:`` block (egress mode, PROXMOX_*
fallbacks, etc.) were silently dead in production — they only ever reached the
``applicant-ui`` container, never the engine. This test pins ``api`` now
carrying the same ``env_file`` wiring as ``applicant-ui``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.prod.yml"


def _load_compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text())


@pytest.mark.unit
def test_compose_parses_with_nonempty_services():
    spec = _load_compose()
    assert isinstance(spec, dict)
    services = spec.get("services")
    assert isinstance(services, dict)
    assert services  # non-empty


@pytest.mark.unit
def test_api_service_has_env_file_referencing_dotenv():
    spec = _load_compose()
    api = spec["services"]["api"]

    env_file = api.get("env_file")
    assert env_file, "api service is missing an env_file directive"

    # The repo uses the long-form dict entry: {path: ../.env, required: false}.
    assert isinstance(env_file, list)
    assert len(env_file) >= 1
    entry = env_file[0]
    assert isinstance(entry, dict)
    assert entry.get("path") == "../.env"
    assert entry.get("required") is False


@pytest.mark.unit
def test_applicant_ui_env_file_still_references_dotenv():
    # Regression guard on the working half — applicant-ui already had this
    # wiring; make sure the api fix didn't accidentally clobber it.
    spec = _load_compose()
    ui = spec["services"]["applicant-ui"]

    env_file = ui.get("env_file")
    assert env_file, "applicant-ui service is missing an env_file directive"
    assert isinstance(env_file, list)
    entry = env_file[0]
    assert isinstance(entry, dict)
    assert entry.get("path") == "../.env"
    assert entry.get("required") is False
