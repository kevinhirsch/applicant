"""Coherence gate for the front-door retirement prep (#857).

This test file asserts that the tooling (runbook + rollback) exists and
that the target invariants of the retirement plan are coherently documented.
It does NOT assert the cutover has happened — it proves the PREP is coherent.
"""

import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = PROJECT_ROOT / "docker" / "docker-compose.prod.yml"
DOC_OPTS = PROJECT_ROOT / "docs" / "ops"
RUNBOOK = DOC_OPTS / "front-door-retirement.md"
ROLLBACK = DOC_OPTS / "front-door-rollback.md"


def _load_compose(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class TestFrontDoorRetirementReadiness:
    """Verifies the prep tooling for the front-door cutover is coherent."""

    def test_runbook_exists(self):
        """D1: runbook must exist and describe the cutover."""
        assert RUNBOOK.exists(), f"Runbook not found at {RUNBOOK}"
        text = RUNBOOK.read_text()
        assert "front-door-retirement" in text
        assert "cutover" in text.lower()

    def test_rollbook_exists(self):
        """D2: rollback procedure must exist."""
        assert ROLLBACK.exists(), f"Rollback doc not found at {ROLLBACK}"
        text = ROLLBACK.read_text()
        assert "front-door-retirement" in text
        assert "rollback" in text.lower()

    def test_prod_compose_is_parseable(self):
        """The prod compose file must parse as valid YAML."""
        assert PROD_COMPOSE.exists(), f"Prod compose not found at {PROD_COMPOSE}"
        compose = _load_compose(PROD_COMPOSE)
        assert "services" in compose

    def test_a0_service_exists_and_has_public_port(self):
        """The runbook's target 'a0' service must exist and expose a host port."""
        compose = _load_compose(PROD_COMPOSE)
        assert "a0" in compose.get("services", {}), "a0 service not found in prod compose"
        a0 = compose["services"]["a0"]
        ports = a0.get("ports", [])
        assert len(ports) > 0, "a0 must have at least one port mapping (public entry)"
        assert any(":80" in p for p in ports), (
            "a0 must map to container port 80 (the public front door)"
        )

    def test_companion_service_has_no_public_port(self):
        """The runbook's target 'companion' service must have NO host port."""
        compose = _load_compose(PROD_COMPOSE)
        assert "companion" in compose.get("services", {}), (
            "companion service not found in prod compose"
        )
        companion = compose["services"]["companion"]
        ports = companion.get("ports", [])
        assert len(ports) == 0, (
            "companion must have NO host port mapping (headless internal)"
        )

    def test_api_service_has_no_public_port(self):
        """The engine 'api' service must have NO host port (internal only)."""
        compose = _load_compose(PROD_COMPOSE)
        assert "api" in compose.get("services", {}), (
            "api service not found in prod compose"
        )
        api_svc = compose["services"]["api"]
        ports = api_svc.get("ports", [])
        assert len(ports) == 0, (
            "api must have NO host port mapping (internal engine only)"
        )

    def test_documents_reference_real_compose_files(self):
        """Runbook and rollback must reference the real compose files."""
        runbook_text = RUNBOOK.read_text()
        rollback_text = ROLLBACK.read_text()
        assert "docker-compose.prod.yml" in runbook_text, (
            "Runbook must reference docker-compose.prod.yml"
        )
        assert "docker-compose.prod.yml" in rollback_text, (
            "Rollback must reference docker-compose.prod.yml"
        )

    def test_documents_reference_real_service_names(self):
        """Runbook must name the actual services (a0, api, companion)."""
        runbook_text = RUNBOOK.read_text()
        assert "a0" in runbook_text, "Runbook must reference service 'a0'"
        assert "api" in runbook_text, "Runbook must reference service 'api'"
        assert "companion" in runbook_text, (
            "Runbook must reference service 'companion'"
        )

    def test_docs_dir_under_version_control(self):
        """Ensure the docs/ops/ directory exists."""
        assert DOC_OPTS.exists(), f"docs/ops/ not found at {DOC_OPTS}"
