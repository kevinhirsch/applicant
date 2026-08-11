"""Keyless Ashby + SmartRecruiters + Workday ATS discovery sources (NFR-EXT-1,
EPIC BREADTH 2026-08-11).

Mirrors ``test_discovery_greenhouse_lever.py``'s pattern exactly: a comma-
separated operator-supplied config list reaches ``build_default_discovery`` and
produces a real, searchable source for EACH configured org/company/board token --
without any change to core/ports. The byte-identical-when-unset guarantee is the
anchor: with the three new env vars empty (the default), ZERO new sources
register and discovery is identical to before.

Workday is the connector that reaches Kevin's PRIMARY target industries
(financial services, healthcare, insurance, consulting) -- verified live against
Wells Fargo, Capital One, Fidelity, Cigna, Nationwide, Travelers, USAA, PayPal,
Vanguard, Humana, CVS Health, Banner Health, Accenture, and Booz Allen Hamilton.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.factory import (
    ASHBY_ORGS,
    SMARTRECRUITERS_COMPANIES,
    WORKDAY_BOARDS,
    build_default_discovery,
)
from applicant.app.config import get_settings
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_empty_setting_registers_zero_new_ats_sources_byte_identical():
    disc = build_default_discovery(live=False)
    sources = disc.available_sources()
    assert not [k for k in sources if k.startswith("ashby:")]
    assert not [k for k in sources if k.startswith("smartrecruiters:")]
    assert not [k for k in sources if k.startswith("workday:")]
    assert "sample" in sources  # existing registry untouched


def test_configured_tokens_add_distinct_keyed_sources_alongside_existing():
    disc = build_default_discovery(
        live=False,
        ashby_orgs=("acme", "globex"),
        smartrecruiters_companies=("widgets",),
        workday_boards=("wf.wd1.myworkdayjobs.com|wf|WellsFargoJobs|Wells Fargo",),
    )
    sources = disc.available_sources()
    assert "ashby:acme" in sources
    assert "ashby:globex" in sources
    assert "smartrecruiters:widgets" in sources
    # Workday's registry key uses just the tenant segment, not the raw compound
    # "host|tenant|site|Display Name" token.
    assert "workday:wf" in sources
    assert "sample" in sources
    assert "jobspy:indeed" in sources


def test_configured_sources_actually_produce_discovered_postings():
    """Reachability proof (CLAUDE.md principle #2): a configured token isn't just
    registered -- running ``search`` against it (via the SAME offline Fake clients
    every other discovery source uses) actually yields postings tagged with the
    configured source key."""
    disc = build_default_discovery(
        live=False,
        ashby_orgs=("acme",),
        smartrecruiters_companies=("widgets",),
        workday_boards=("wf.wd1.myworkdayjobs.com|wf|WellsFargoJobs|Wells Fargo",),
    )
    criteria = SearchCriteria(campaign_id=CampaignId(new_id()))

    ab = disc.search(CampaignId(new_id()), criteria, sources=["ashby:acme"])
    assert ab, "a configured Ashby org must yield discovered postings"
    assert all(p.source_key == "ashby:acme" for p in ab)
    assert all(p.company == "acme" for p in ab)
    assert all(p.easy_apply is True for p in ab)

    sr = disc.search(CampaignId(new_id()), criteria, sources=["smartrecruiters:widgets"])
    assert sr, "a configured SmartRecruiters company must yield discovered postings"
    assert all(p.source_key == "smartrecruiters:widgets" for p in sr)
    assert all(p.easy_apply is True for p in sr)

    wd = disc.search(CampaignId(new_id()), criteria, sources=["workday:wf"])
    assert wd, "a configured Workday board must yield discovered postings"
    assert all(p.source_key == "workday:wf" for p in wd)
    assert all(p.easy_apply is True for p in wd)


def test_the_container_threads_configured_ats_sources_into_discovery(monkeypatch):
    """Reachability through the PROPER layer: ``container.py`` reads the configured
    settings and injects them into ``build_default_discovery`` (exactly as it does
    for ``greenhouse_boards``/``lever_companies``)."""
    from applicant.app.config import Settings
    from applicant.app.container import build_container

    monkeypatch.setenv("DISCOVERY_ASHBY_ORGS", "acme,globex")
    monkeypatch.setenv("DISCOVERY_SMARTRECRUITERS_COMPANIES", "widgets")
    monkeypatch.setenv(
        "DISCOVERY_WORKDAY_BOARDS",
        "wf.wd1.myworkdayjobs.com|wf|WellsFargoJobs|Wells Fargo",
    )
    get_settings.cache_clear()
    container = build_container(Settings())
    sources = container.discovery.available_sources()
    assert "ashby:acme" in sources
    assert "ashby:globex" in sources
    assert "smartrecruiters:widgets" in sources
    assert "workday:wf" in sources


def test_settings_default_ats_sources_are_empty_strings(monkeypatch):
    """Pins the Settings FIELD default (Field(default="", ...)), isolated from
    whatever this checkout's own .env happens to contain (mirrors the equivalent
    Greenhouse/Lever test's rationale)."""
    from applicant.app.config import Settings

    for var in (
        "DISCOVERY_ASHBY_ORGS",
        "DISCOVERY_SMARTRECRUITERS_COMPANIES",
        "DISCOVERY_WORKDAY_BOARDS",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.discovery_ashby_orgs == ""
    assert settings.discovery_smartrecruiters_companies == ""
    assert settings.discovery_workday_boards == ""


def test_hardcoded_ats_constant_keys_are_empty_by_default():
    """The hardcoded registries ship empty by default -- actual board lists are
    additive via the env vars above (same wave-one shape as Greenhouse/Lever)."""
    assert ASHBY_ORGS == {}
    assert SMARTRECRUITERS_COMPANIES == {}
    assert WORKDAY_BOARDS == {}


@pytest.mark.unit
class TestWorkdayCompoundToken:
    def test_malformed_token_degrades_to_empty_never_crashes(self):
        """A malformed Workday token (missing pipe segments) must be caught by the
        source's own broad except -- never crash the whole discovery run (H2, same
        resilience contract every other source honors)."""
        from applicant.adapters.discovery.clients import LiveWorkdayClient
        from applicant.adapters.discovery.jobspy_searxng import WorkdaySource

        src = WorkdaySource(client=LiveWorkdayClient(), token="not-a-valid-token", key="workday:bad")
        out = src.fetch(CampaignId(new_id()), SearchCriteria(campaign_id=CampaignId(new_id())))
        assert out == []
        assert src.last_error is not None

    def test_display_name_segment_is_optional(self):
        from applicant.adapters.discovery.clients import FakeWorkdayClient
        from applicant.adapters.discovery.jobspy_searxng import WorkdaySource

        # 3-segment token (no display name) -> falls back to the tenant as company.
        src = WorkdaySource(
            client=FakeWorkdayClient(), token="acme.wd1.myworkdayjobs.com|acme|External"
        )
        out = src.fetch(CampaignId(new_id()), SearchCriteria(campaign_id=CampaignId(new_id())))
        assert out
        assert all(p.company == "acme" for p in out)
