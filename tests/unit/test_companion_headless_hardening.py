"""Hermetic test: companion is a headless internal-only service (no public port).

The companion must NOT publish a host port; the engine reaches it in-network at
http://companion:7000 over the token-gated /api/applicant/internal/* channel.
"""

import pytest
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = PROJECT_ROOT / "docker" / "docker-compose.prod.yml"


def _load_compose(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


SVC_NAMES = ("companion", "api", "a0")


class TestCompanionHeadlessHardening:
    """Assert the companion is internal-only with intact engine wiring."""

    def test_prod_compose_parseable(self):
        """docker-compose.prod.yml must be valid YAML."""
        assert PROD_COMPOSE.exists(), f"Prod compose not found at {PROD_COMPOSE}"
        compose = _load_compose(PROD_COMPOSE)
        assert "services" in compose

    @pytest.mark.parametrize("service", SVC_NAMES)
    def test_required_services_exist(self, service):
        """All required services must be defined."""
        compose = _load_compose(PROD_COMPOSE)
        assert service in compose.get("services", {}), (
            f"Required service {service!r} not found in prod compose"
        )

    def test_companion_has_no_public_host_port(self):
        """The companion service must publish NO host port (internal-only)."""
        compose = _load_compose(PROD_COMPOSE)
        companion = compose["services"]["companion"]
        ports = companion.get("ports", [])
        assert len(ports) == 0, (
            f"companion must have NO host port mapping (got {ports!r}). "
            "Remove the host-side publish so the container is only reachable "
            "on the internal docker network at http://companion:7000."
        )

    def test_companion_still_internal_network(self):
        """The companion must NOT be in a separate 'profiles' or gated behind
        a non-default profile that would break internal reachability."""
        compose = _load_compose(PROD_COMPOSE)
        companion = compose["services"]["companion"]
        # If it has profiles, it won't start by default
        profiles = companion.get("profiles", [])
        assert len(profiles) == 0, (
            f"companion must not be profile-gated (got profiles={profiles!r})"
        )

    def test_companion_has_healthcheck(self):
        """Internal service must still have a healthcheck for Docker orchestration."""
        compose = _load_compose(PROD_COMPOSE)
        companion = compose["services"]["companion"]
        healthcheck = companion.get("healthcheck")
        assert healthcheck is not None, "companion should declare a healthcheck"
        assert "test" in healthcheck, "healthcheck must have a test command"

    def test_companion_depends_on_api_healthy(self):
        """Companion must wait for the engine to be healthy."""
        compose = _load_compose(PROD_COMPOSE)
        companion = compose["services"]["companion"]
        depends = companion.get("depends_on", {})
        assert "api" in depends, "companion must depend_on the api service"
        api_dep = depends["api"]
        assert api_dep.get("condition") == "service_healthy", (
            "companion should wait for api health, not just service_started"
        )

    def test_engine_wiring_mind_backend_is_bridge(self):
        """The engine must carry MIND_BACKEND=bridge to read companion memory."""
        compose = _load_compose(PROD_COMPOSE)
        api_svc = compose["services"]["api"]
        env = api_svc.get("environment", {})
        raw = env.get("MIND_BACKEND", "")
        # MIND_BACKEND: ${MIND_BACKEND:-bridge} resolves to 'bridge' when unset
        # Check either 'bridge' or the template default
        assert "bridge" in raw, (
            "engine MIND_BACKEND must default to 'bridge' for companion integration "
            f"(got {raw!r})"
        )

    def test_engine_wiring_workspace_url_points_at_companion(self):
        """The engine must reach the companion at http://companion:7000."""
        compose = _load_compose(PROD_COMPOSE)
        api_svc = compose["services"]["api"]
        env = api_svc.get("environment", {})
        url = env.get("WORKSPACE_URL", "")
        assert "companion:7000" in url, (
            f"engine WORKSPACE_URL must point at http://companion:7000 (got {url!r})"
        )

    def test_engine_wiring_internal_token_present(self):
        """The engine must reference APPLICANT_INTERNAL_TOKEN for callback auth."""
        compose = _load_compose(PROD_COMPOSE)
        api_svc = compose["services"]["api"]
        env = api_svc.get("environment", {})
        token_var = env.get("APPLICANT_INTERNAL_TOKEN", "")
        assert "APPLICANT_INTERNAL_TOKEN" in token_var or token_var, (
            "engine must reference APPLICANT_INTERNAL_TOKEN "
            f"(got {token_var!r})"
        )

    def test_a0_service_has_public_port(self):
        """The a0 service (not companion) is the public entry."""
        compose = _load_compose(PROD_COMPOSE)
        a0 = compose["services"]["a0"]
        ports = a0.get("ports", [])
        assert len(ports) > 0, "a0 must have at least one port mapping (public entry)"
        assert any(":80" in p for p in ports), (
            "a0 must publish a port mapping to container port 80"
        )

    def test_engine_api_has_no_public_port(self):
        """The api (engine) must also be internal-only."""
        compose = _load_compose(PROD_COMPOSE)
        api_svc = compose["services"]["api"]
        ports = api_svc.get("ports", [])
        assert len(ports) == 0, (
            f"api must have NO host port mapping (got {ports!r})"
        )

    def test_companion_has_expose_not_ports(self):
        """Companion may use 'expose:' to document its container port without publishing."""
        compose = _load_compose(PROD_COMPOSE)
        companion = compose["services"]["companion"]
        # No 'expose' is also fine — ports are documented in healthcheck and env wiring
        expose = companion.get("expose", [])
        ports = companion.get("ports", [])
        assert len(ports) == 0, "companion must not have ports:"
