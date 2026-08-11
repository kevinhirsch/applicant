"""Keyless Greenhouse + Lever ATS discovery sources (NFR-EXT-1).

Mirrors the item-80 RSS-feed pattern: a comma-separated operator-supplied config
list reaches ``build_default_discovery`` and produces a real, searchable source for
EACH configured board token / company slug — without any change to core/ports.

The byte-identical-when-unset guarantee (item 80's unset test) is the anchor: with
``DISCOVERY_GREENHOUSE_BOARDS`` / ``DISCOVERY_LEVER_COMPANIES`` empty (the default),
ZERO new sources register and discovery is identical to before.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.factory import (
    GREENHOUSE_BOARD_TOKENS,
    LEVER_COMPANIES,
    build_default_discovery,
)
from applicant.app.config import get_settings
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """``get_settings`` is ``@lru_cache``-d (one instance per process); clear it
    before AND after so an env-var mutation in one test never leaks into the
    next (mirrors ``tests/conftest.py``'s own ``get_settings.cache_clear()``
    idiom around ``DATABASE_URL``/``CHECKPOINT_DIR``)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_empty_setting_registers_zero_ats_sources_byte_identical():
    """An unconfigured ``discovery_greenhouse_boards`` / ``discovery_lever_companies``
    (the default, "") must NOT change the source registry at all — no Greenhouse or
    Lever sources exist, exactly like before this change."""
    disc = build_default_discovery(live=False)
    sources = disc.available_sources()
    assert not [k for k in sources if k.startswith("greenhouse:")]
    assert not [k for k in sources if k.startswith("lever:")]
    assert "rss:hn-hiring" in sources  # existing registry untouched
    assert "sample" in sources


def test_configured_tokens_add_distinct_keyed_sources_alongside_existing():
    """The ``greenhouse_boards`` / ``lever_companies`` kwargs add NEW sources with
    distinct keys ALONGSIDE the hardcoded defaults — the merge is additive, never
    a replacement."""
    disc = build_default_discovery(
        live=False,
        greenhouse_boards=("acme", "globex"),
        lever_companies=("widgets",),
    )
    sources = disc.available_sources()
    assert "greenhouse:acme" in sources
    assert "greenhouse:globex" in sources
    assert "lever:widgets" in sources
    # existing sources untouched
    assert "sample" in sources
    assert "rss:hn-hiring" in sources
    assert "jobspy:indeed" in sources


def test_configured_sources_actually_produce_discovered_postings():
    """Reachability proof (CLAUDE.md principle #2): a configured Greenhouse token or
    Lever company isn't just registered — running ``search`` against it (via the
    SAME offline Fake clients every other discovery source uses) actually yields
    postings tagged with the configured source key."""
    disc = build_default_discovery(
        live=False,
        greenhouse_boards=("acme",),
        lever_companies=("widgets",),
    )
    criteria = SearchCriteria(campaign_id=CampaignId(new_id()))
    gh = disc.search(CampaignId(new_id()), criteria, sources=["greenhouse:acme"])
    assert gh, "a configured Greenhouse board must yield discovered postings"
    assert all(p.source_key == "greenhouse:acme" for p in gh)
    assert all(p.company == "acme" for p in gh)  # configured token is the display name
    lv = disc.search(CampaignId(new_id()), criteria, sources=["lever:widgets"])
    assert lv, "a configured Lever company must yield discovered postings"
    assert all(p.source_key == "lever:widgets" for p in lv)
    assert all(p.company == "widgets" for p in lv)


def test_the_container_threads_configured_ats_sources_into_discovery(monkeypatch):
    """Reachability through the PROPER layer: ``container.py`` reads the configured
    settings and injects them into ``build_default_discovery`` (exactly as it does
    for ``rss_feeds``), so a boot-configured ATS directory reaches the live discovery
    adapter. The adapter itself never imports ``app.config`` — that would break the
    hexagonal layering contract (NFR-ARCH-1), so the wiring lives here."""
    from applicant.app.config import Settings
    from applicant.app.container import build_container

    monkeypatch.setenv("DISCOVERY_GREENHOUSE_BOARDS", "acme,globex")
    monkeypatch.setenv("DISCOVERY_LEVER_COMPANIES", "widgets")
    get_settings.cache_clear()
    container = build_container(Settings())
    sources = container.discovery.available_sources()
    assert "greenhouse:acme" in sources
    assert "greenhouse:globex" in sources
    assert "lever:widgets" in sources


def test_settings_default_ats_sources_are_empty_strings():
    """Pins the Settings FIELD default (Field(default="", ...)), not whatever
    happens to be configured in this repo's actual .env right now.

    ``get_settings()``/``Settings()`` read the repo-root ``.env`` (see
    ``SettingsConfigDict(env_file=".env", ...)``) -- and since the 2026-08-07
    keyless ATS discovery connectors were deployed, this repo's own .env
    deliberately seeds ``DISCOVERY_GREENHOUSE_BOARDS``/``DISCOVERY_LEVER_
    COMPANIES`` with ~20-30 real companies (see docs / the ATS-discovery
    deploy notes). That's correct, live, intentional configuration for this
    checkout, not a stale/broken default -- so it must not leak into an
    unrelated Settings instance built here. ``_env_file=None`` bypasses the
    .env file entirely, isolating the field's true class-level default from
    whatever this particular checkout's .env happens to contain.
    """
    from applicant.app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.discovery_greenhouse_boards == ""
    assert settings.discovery_lever_companies == ""


def test_hardcoded_ats_constant_keys_are_empty_by_default():
    """The hardcoded Greenhouse/Lever registries are empty by default, matching the
    add-new-source-via-config shape (no hardcoded defaults ship in wave one)."""
    assert GREENHOUSE_BOARD_TOKENS == {}
    assert LEVER_COMPANIES == {}
