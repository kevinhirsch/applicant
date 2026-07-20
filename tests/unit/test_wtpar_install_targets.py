"""WT (#686) — static coherence assertions between scripts/install.sh
and docker/docker-compose.prod.yml: the one-command install path must be
consistent — every referenced service exists, env vars are wired, and the
compose file the installer uses is the same one being tested.

Pure static assertions — no docker, no compose config validation.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL_PATH = REPO / "scripts/install.sh"
COMPOSE_PATH = REPO / "docker/docker-compose.prod.yml"


@pytest.fixture(scope="module")
def install_sh() -> str:
    return INSTALL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose_yml() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


class TestInstallTargets:
    """Static coherence: the install.sh one-liner and the prod compose file agree."""

    # ── Compose file structure ────────────────────────────────────────────

    def test_compose_file_exists(self):
        assert COMPOSE_PATH.is_file(), f"Compose file missing at {COMPOSE_PATH}"

    def test_install_file_exists(self):
        assert INSTALL_PATH.is_file(), f"Install script missing at {INSTALL_PATH}"

    def test_compose_has_known_services(self, compose_yml):
        """All services the stack depends on are defined in the compose file."""
        assert "a0:" in compose_yml, "a0 service not found in compose"
        assert "api:" in compose_yml, "api service not found in compose"
        assert "postgres:" in compose_yml, "postgres service not found in compose"
        assert "searxng:" in compose_yml, "searxng service not found in compose"
        assert "companion:" in compose_yml, "companion service not found in compose"
        assert "chromadb:" in compose_yml, "chromadb service not found in compose"
        assert "ntfy:" in compose_yml, "ntfy service not found in compose"
        assert "updater:" in compose_yml, "updater service not found in compose"

    def test_compose_has_named_volumes(self, compose_yml):
        """The volumes section contains all required named volumes."""
        assert "a0-data:" in compose_yml
        assert "pgdata:" in compose_yml
        assert "pgbackups:" in compose_yml
        assert "checkpoints:" in compose_yml
        assert "secrets:" in compose_yml
        assert "fonts:" in compose_yml
        assert "browser-profiles:" in compose_yml
        assert "ui-data:" in compose_yml
        assert "chromadb-data:" in compose_yml
        assert "searxng-data:" in compose_yml
        assert "ntfy-cache:" in compose_yml
        assert "update-control:" in compose_yml

    # ── a0 service wiring ─────────────────────────────────────────────────

    def test_a0_depends_on_api_healthy(self, compose_yml):
        """a0 gates on api: service_healthy so it does not serve before engine is ready."""
        a0_block = _service_block(compose_yml, "a0:")
        assert "depends_on:" in a0_block
        assert "api:" in a0_block
        assert "condition: service_healthy" in a0_block

    def test_a0_engine_url_env(self, compose_yml):
        """a0 sends ENGINE_URL=http://api:8000 to the container environment."""
        a0_block = _service_block(compose_yml, "a0:")
        assert "ENGINE_URL" in a0_block
        assert "http://api:8000" in a0_block

    def test_a0_publishes_port(self, compose_yml):
        """a0 publishes the public APP_PORT -> container port 80."""
        a0_block = _service_block(compose_yml, "a0:")
        assert "APP_PORT" in a0_block or "8000:80" in a0_block

    def test_a0_has_mcp_env(self, compose_yml):
        """a0 pre-registers the engine MCP server via A0_SET_MCP_SERVERS."""
        a0_block = _service_block(compose_yml, "a0:")
        assert "A0_SET_MCP_SERVERS" in a0_block
        assert "applicant-engine" in a0_block
        assert "/mcp" in a0_block

    def test_a0_restart_always(self, compose_yml):
        a0_block = _service_block(compose_yml, "a0:")
        assert "restart: always" in a0_block

    # ── api service wiring ────────────────────────────────────────────────

    def test_api_env_file_passthrough(self, compose_yml):
        """The api service loads the repo-root .env for ~50 engine vars."""
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "env_file:" in api_block
        assert ".env" in api_block

    def test_api_database_url_wired(self, compose_yml):
        """The api DATABASE_URL uses postgres service in-network."""
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "DATABASE_URL: postgresql+psycopg" in api_block
        assert "@postgres:5432/" in api_block

    def test_api_expose_internal_only(self, compose_yml):
        """api is internal only (expose 8000, no published ports)."""
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "expose:" in api_block
        assert '"8000"' in api_block
        # Confirms ports: does NOT appear in the api block itself
        # (takeover-desktop later also has ports: but that's a separate service)
        api_fragment = _service_block(compose_yml, "  api:\n    build", end_marker="takeover-desktop")
        assert "ports:" not in api_fragment

    def test_api_depends_on_postgres_healthy(self, compose_yml):
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "depends_on:" in api_block
        assert "postgres:" in api_block
        assert "condition: service_healthy" in api_block

    def test_api_healthcheck_present(self, compose_yml):
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "healthcheck:" in api_block
        assert "/healthz" in api_block

    def test_api_volumes_mounted(self, compose_yml):
        """api mounts checkpoints, secrets, fonts, browser-profiles, update-control."""
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "checkpoints:" in api_block
        assert "secrets:" in api_block
        assert "fonts:" in api_block
        assert "browser-profiles:" in api_block
        assert "update-control:" in api_block

    def test_api_restart_always(self, compose_yml):
        api_block = _service_block(compose_yml, "  api:\n    build")
        assert "restart: always" in api_block

    # ── install.sh coherence ──────────────────────────────────────────────

    def test_install_refers_to_correct_compose_file(self, install_sh):
        """install.sh hard-codes this exact compose file path."""
        assert "docker/docker-compose.prod.yml" in install_sh
        assert "COMPOSE_FILE" in install_sh

    def test_install_builds_a0_and_api(self, install_sh):
        """The build step targets both locally-built images."""
        assert "build a0 api" in install_sh

    def test_install_brings_up_full_stack(self, install_sh):
        """The up step brings up all known services."""
        assert "Bringing up the full stack (UI + api + postgres + searxng + chromadb + ntfy)" in install_sh

    def test_install_persists_postgres_password(self, install_sh):
        """install.sh generates and persists POSTGRES_PASSWORD to .env."""
        assert "POSTGRES_PASSWORD" in install_sh

    def test_install_persists_internal_token(self, install_sh):
        """install.sh generates APPLICANT_INTERNAL_TOKEN for bidirectional bridge."""
        assert "APPLICANT_INTERNAL_TOKEN" in install_sh

    def test_install_persists_searxng_secret(self, install_sh):
        """install.sh handles SEARXNG_SECRET generation."""
        assert "SEARXNG_SECRET" in install_sh

    def test_install_bootstraps_self_when_piped(self, install_sh):
        """install.sh detects stdin-piped execution and clones the repo."""
        assert 'bash -c "$(curl -fsSL' in install_sh
        assert "Detached run" in install_sh or "bootstrapping" in install_sh.lower()

    def test_install_has_doctor_self_check(self, install_sh):
        assert "--doctor" in install_sh
        assert "health self-check" in install_sh or "Health" in install_sh

    def test_install_has_uninstall_and_purge_modes(self, install_sh):
        assert "--uninstall" in install_sh
        assert "--purge" in install_sh

    def test_install_has_health_monitor(self, install_sh):
        assert "monitor_health" in install_sh
        assert "Health" in install_sh or "health" in install_sh


def _service_block(yml: str, anchor: str, end_marker: str | None = None) -> str:
    """Extract the YAML block for a given service anchor.
    Returns the text from anchor to the next key at the same indent level or end_marker.
    """
    idx = yml.index(anchor)
    rest = yml[idx:]
    lines = rest.split("\n")
    # Determine the indent of the first line of the anchor
    first_anchor_line = anchor.split("\n")[0]
    indent = len(first_anchor_line) - len(first_anchor_line.lstrip())
    block_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # Preserve blank lines and comments within the block
            block_lines.append(line)
            continue
        if not block_lines:
            block_lines.append(line)
            continue
        # Compute indent of this line
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent <= indent:
            # Same or lesser indent — new sibling block reached
            if end_marker and end_marker in line:
                break
            break
        block_lines.append(line)
    return "\n".join(block_lines)
