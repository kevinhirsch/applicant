"""EPIC STEALTH (ST-2/ST-5): selective per-source proxy application + block-detect
residential escalation, wired through the existing ``ProxyConfig`` seam.

Covers both the factory (which egress each source is built with) and the
``JobSpySource`` runtime escalation (retry through the residential proxy on a
bot-block), and proves the ``stealth=None`` path stays byte-identical.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.factory import build_default_discovery
from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySource,
    PerBoardRateLimiter,
    ProxyConfig,
)
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id
from applicant.core.stealth_policy import PROXY_POLICY_VPS, build_stealth_config

RESIDENTIAL = "http://10.8.0.1:8880"


def _criteria() -> tuple[CampaignId, SearchCriteria]:
    cid = CampaignId(new_id())
    return cid, SearchCriteria(campaign_id=cid)


# --- factory: selective per-source egress ----------------------------------
@pytest.mark.unit
class TestFactorySelectiveEgress:
    def test_block_prone_jobspy_sources_get_residential(self):
        stealth = build_stealth_config(residential_proxy_url=RESIDENTIAL)
        disc = build_default_discovery(stealth=stealth)
        for site in ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter"):
            src = disc._sources[f"jobspy:{site}"]
            assert src._proxy.as_list() == [RESIDENTIAL]

    def test_keyless_ats_and_searxng_stay_direct(self):
        stealth = build_stealth_config(residential_proxy_url=RESIDENTIAL)
        disc = build_default_discovery(
            live=True,
            searxng_url="http://searxng:8080",
            stealth=stealth,
            greenhouse_boards=("acme",),
            lever_companies=("widgets",),
        )
        # SearXNG (your own instance) and RSS are direct.
        assert disc._sources["searxng"]._proxy.as_list() is None
        assert disc._sources["rss:hn-hiring"]._proxy.as_list() is None
        # Keyless ATS sources carry no proxy at all (always direct, zero GB).
        assert getattr(disc._sources["greenhouse:acme"], "_proxy", None) is None
        assert getattr(disc._sources["lever:widgets"], "_proxy", None) is None

    def test_sticky_sessid_decorates_the_residential_proxy(self):
        stealth = build_stealth_config(residential_proxy_url=RESIDENTIAL)
        disc = build_default_discovery(stealth=stealth, flow_sessid="run42")
        src = disc._sources["jobspy:linkedin"]
        assert src._proxy.as_list() == ["http://sessid-run42@10.8.0.1:8880"]

    def test_vps_baseline_sets_a_residential_escalation_proxy(self):
        # With block-prone sources starting on vps (no vps URL => direct), the
        # residential pool becomes the block-detect escalation target.
        stealth = build_stealth_config(
            residential_proxy_url=RESIDENTIAL, block_prone_policy=PROXY_POLICY_VPS
        )
        disc = build_default_discovery(stealth=stealth)
        src = disc._sources["jobspy:indeed"]
        assert src._proxy.as_list() is None  # baseline direct/vps
        assert src._escalation_proxy is not None
        assert src._escalation_proxy.as_list() == [RESIDENTIAL]

    def test_no_escalation_when_already_residential(self):
        stealth = build_stealth_config(residential_proxy_url=RESIDENTIAL)
        disc = build_default_discovery(stealth=stealth)
        # baseline IS residential, so there's nothing to escalate to.
        assert disc._sources["jobspy:indeed"]._escalation_proxy is None

    def test_rate_limiter_built_from_pacing_knobs(self):
        stealth = build_stealth_config(
            residential_proxy_url=RESIDENTIAL, rate_max_calls=9, rate_period_seconds=120.0
        )
        disc = build_default_discovery(stealth=stealth)
        assert isinstance(disc._rate_limiter, PerBoardRateLimiter)
        assert disc._rate_limiter._max_calls == 9
        assert disc._rate_limiter._period == 120.0

    def test_stealth_none_is_byte_identical_legacy_path(self):
        # No stealth policy => the shared FR-DISC-6 proxy governs every source and
        # no escalation is configured (the pre-epic behavior).
        disc = build_default_discovery(proxies=("http://legacy:8080",))
        src = disc._sources["jobspy:linkedin"]
        assert src._proxy.as_list() == ["http://legacy:8080"]
        assert src._escalation_proxy is None


# --- JobSpySource: block-detect residential escalation ---------------------
class _BlockThenResidentialClient:
    """Blocks on the direct exit; succeeds only when the residential proxy is used."""

    def __init__(self, residential: str) -> None:
        self._residential = residential
        self.proxies_seen: list[list[str] | None] = []

    def scrape(self, *, site, search_term, location, results_wanted, proxies, **kw):
        self.proxies_seen.append(proxies)
        if proxies and self._residential in proxies:
            return [
                {
                    "title": "Senior Backend Engineer",
                    "company": "Acme",
                    "job_url": "https://x.test/senior-backend",
                    "description": "Python, FastAPI.",
                }
            ]
        raise RuntimeError(f"{site} blocked the request (HTTP 403)")


class _AlwaysErrorClient:
    """Fails with a NON-block error every time (must never escalate)."""

    def __init__(self) -> None:
        self.calls = 0

    def scrape(self, *, site, search_term, location, results_wanted, proxies, **kw):
        self.calls += 1
        raise ValueError("connection reset by peer")


@pytest.mark.unit
class TestJobSpyEscalation:
    def test_block_triggers_residential_retry_and_recovers(self):
        cid, criteria = _criteria()
        client = _BlockThenResidentialClient(RESIDENTIAL)
        src = JobSpySource(
            site="glassdoor",
            client=client,
            proxy=ProxyConfig(),  # direct baseline
            escalation_proxy=ProxyConfig(proxies=(RESIDENTIAL,), enabled=True),
        )
        postings = src.fetch(cid, criteria)
        assert len(postings) == 1
        assert postings[0].title == "Senior Backend Engineer"
        assert src.used_escalation is True
        assert src.last_error is None
        # First attempt direct (None), second through the residential proxy.
        assert client.proxies_seen[0] is None
        assert client.proxies_seen[1] == [RESIDENTIAL]

    def test_non_block_error_never_escalates(self):
        cid, criteria = _criteria()
        client = _AlwaysErrorClient()
        src = JobSpySource(
            site="indeed",
            client=client,
            proxy=ProxyConfig(),
            escalation_proxy=ProxyConfig(proxies=(RESIDENTIAL,), enabled=True),
        )
        assert src.fetch(cid, criteria) == []
        assert client.calls == 1  # no retry
        assert src.used_escalation is False
        assert src.last_error == "connection reset by peer"

    def test_no_escalation_configured_is_legacy_behavior(self):
        cid, criteria = _criteria()
        client = _BlockThenResidentialClient(RESIDENTIAL)
        src = JobSpySource(site="glassdoor", client=client, proxy=ProxyConfig())
        assert src.fetch(cid, criteria) == []  # blocked, no recovery
        assert src.used_escalation is False
        assert src.last_error is not None and "403" in src.last_error

    def test_escalation_retries_up_to_the_configured_count(self):
        """A rotating residential exit that blocks once then succeeds is recovered
        when ``escalation_max_retries`` allows a second attempt (models a per-attempt
        IP rotation on the residential pool)."""
        cid, criteria = _criteria()

        class _RotatingResidential:
            def __init__(self) -> None:
                self.residential_attempts = 0

            def scrape(self, *, site, search_term, location, results_wanted, proxies, **kw):
                if not proxies:  # direct baseline: always blocked
                    raise RuntimeError(f"{site} blocked (HTTP 403)")
                self.residential_attempts += 1
                if self.residential_attempts < 2:  # first residential IP still blocked
                    raise RuntimeError(f"{site} blocked (HTTP 429)")
                return [
                    {"title": "Engineer", "company": "Acme", "job_url": "https://x.test/1"}
                ]

        client = _RotatingResidential()
        src = JobSpySource(
            site="indeed",
            client=client,
            proxy=ProxyConfig(),
            escalation_proxy=ProxyConfig(proxies=(RESIDENTIAL,), enabled=True),
            escalation_max_retries=3,
        )
        postings = src.fetch(cid, criteria)
        assert len(postings) == 1
        assert src.used_escalation is True
        assert client.residential_attempts == 2

    def test_escalation_max_retries_wired_from_stealth_config(self):
        stealth = build_stealth_config(
            residential_proxy_url=RESIDENTIAL,
            block_prone_policy=PROXY_POLICY_VPS,  # so escalation is set
            block_max_retries=4,
        )
        disc = build_default_discovery(stealth=stealth)
        assert disc._sources["jobspy:indeed"]._escalation_max_retries == 4

    def test_escalation_also_blocked_reports_error(self):
        cid, criteria = _criteria()

        class _AlwaysBlocked:
            def scrape(self, *, site, search_term, location, results_wanted, proxies, **kw):
                raise RuntimeError(f"{site} blocked (HTTP 429)")

        src = JobSpySource(
            site="linkedin",
            client=_AlwaysBlocked(),
            proxy=ProxyConfig(),
            escalation_proxy=ProxyConfig(proxies=(RESIDENTIAL,), enabled=True),
        )
        assert src.fetch(cid, criteria) == []
        assert src.used_escalation is False
        assert src.last_error is not None
