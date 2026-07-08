"""P2-13 — Source reliability matrix.

Discovery quality tested across MULTIPLE regions and job categories, hermetically
(FR-DISC-*, H2). Real job boards are never reached from this suite — every board is
exercised through the SAME fake-client seam ``clients.py``/``factory.py`` uses for the
default offline lane, with per-scenario canned rows standing in for what each board
would plausibly return (or fail to return) for that region/category.

This proves the code-derived contract: normalization, criteria filtering, per-source
outcome recording (H2), the shortfall vocabulary, and persistence all behave correctly
across a region/category matrix and when boards degrade heterogeneously (one source
errors, another is genuinely empty, others succeed) IN THE SAME RUN. It does NOT prove
live per-region board coverage — that requires a live-deploy drill (see
``tests/integration/test_discovery_live.py``, gated + skipped by default, and
``docs/discovery-source-reliability.md``'s "What this proves" section).
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySearxngDiscovery,
    JobSpySource,
)
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id
from applicant.core.rules.underdelivery import (
    SOURCE_EMPTY,
    SOURCE_ERROR,
    SOURCE_OK,
    discovery_shortfalls,
    source_label,
)


class _ScenarioJobSpyClient:
    """A ``JobSpyClient`` double that returns per-site canned rows, with some
    sites configured to raise (simulating a board that is down/blocked/captcha'd
    for this scenario) so one run can exercise ok/empty/error side by side."""

    def __init__(self, rows_by_site: dict[str, list[dict]], *, raise_for: frozenset[str] = frozenset()):
        self._rows_by_site = rows_by_site
        self._raise_for = raise_for

    def scrape(self, *, site, search_term, location, results_wanted, proxies):
        if site in self._raise_for:
            raise RuntimeError(f"{site} refused the request (simulated block/captcha)")
        return list(self._rows_by_site.get(site, []))[:results_wanted]


# --- the region/category scenario matrix (2 regions x categories + a mixed one) ----
# Three scenarios, each pairing a distinct region with a distinct job category, plus a
# deliberately heterogeneous per-source outcome mix (ok / empty / error) so the same
# run proves the aggregator handles all three without one masking another.
_SCENARIOS = [
    {
        "name": "US-remote engineering",
        "criteria": {"titles": ("Software Engineer",), "locations": ("Remote, US",)},
        "rows_by_site": {
            "indeed": [
                {
                    "title": "Software Engineer",
                    "company": "Acme Corp",
                    "location": "Remote, US",
                    "is_remote": True,
                    "job_url": "https://indeed.test/us-remote-eng-1",
                }
            ],
            "linkedin": [
                {
                    "title": "Senior Software Engineer",
                    "company": "Globex",
                    "location": "Remote, US",
                    "is_remote": True,
                    "job_url": "https://linkedin.test/us-remote-eng-1",
                }
            ],
            # ZipRecruiter genuinely has nothing this check (empty, not an error).
            "zip_recruiter": [],
        },
        "raise_for": frozenset({"glassdoor"}),  # simulated block/captcha wall
        "expect_status": {
            "jobspy:indeed": SOURCE_OK,
            "jobspy:linkedin": SOURCE_OK,
            "jobspy:zip_recruiter": SOURCE_EMPTY,
            "jobspy:glassdoor": SOURCE_ERROR,
        },
    },
    {
        "name": "UK sales",
        "criteria": {"titles": ("Account Executive",), "locations": ("London, UK",)},
        "rows_by_site": {
            "indeed": [
                {
                    "title": "Account Executive",
                    "company": "Barclays",
                    "location": "London, UK",
                    "job_url": "https://indeed.test/uk-sales-1",
                }
            ],
            "linkedin": [],  # no matching postings this check — genuinely empty
        },
        "raise_for": frozenset({"zip_recruiter"}),  # ZipRecruiter is US/CA-only; a
        # live deployment would see this as a hard reject/empty depending on the
        # board's behavior for out-of-region queries — modeled here as an error to
        # prove an out-of-coverage board never silently vanishes either.
        "expect_status": {
            "jobspy:indeed": SOURCE_OK,
            "jobspy:linkedin": SOURCE_EMPTY,
            "jobspy:zip_recruiter": SOURCE_ERROR,
        },
    },
    {
        "name": "Germany data/engineering",
        "criteria": {"titles": ("Data Scientist",), "locations": ("Berlin, Germany",)},
        "rows_by_site": {
            "indeed": [
                {
                    "title": "Data Scientist",
                    "company": "SAP",
                    "location": "Berlin, Germany",
                    "job_url": "https://indeed.test/de-data-1",
                }
            ],
            "linkedin": [
                {
                    "title": "Senior Data Scientist",
                    "company": "Zalando",
                    "location": "Berlin, Germany",
                    "job_url": "https://linkedin.test/de-data-1",
                }
            ],
            "zip_recruiter": [],
            "glassdoor": [],
        },
        # Google's jobs aggregator hits a simulated block/captcha this check, so
        # this scenario too covers ok + empty + error in the SAME run.
        "raise_for": frozenset({"google"}),
        "expect_status": {
            "jobspy:indeed": SOURCE_OK,
            "jobspy:linkedin": SOURCE_OK,
            "jobspy:zip_recruiter": SOURCE_EMPTY,
            "jobspy:glassdoor": SOURCE_EMPTY,
            "jobspy:google": SOURCE_ERROR,
        },
    },
]


def _build_aggregator(scenario: dict) -> JobSpySearxngDiscovery:
    client = _ScenarioJobSpyClient(scenario["rows_by_site"], raise_for=scenario["raise_for"])
    sites = sorted(scenario["expect_status"].keys())
    sources = [JobSpySource(site=key.split(":", 1)[1], client=client) for key in sites]
    return JobSpySearxngDiscovery(sources=sources)


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def embedding() -> LocalEmbedding:
    return LocalEmbedding()


@pytest.mark.unit
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s["name"] for s in _SCENARIOS])
def test_region_category_scenario_normalizes_and_matches(scenario, storage, embedding):
    """Every scenario's postings normalize correctly and match the stated criteria,
    regardless of region/category — normalization/matching never special-case a
    region or a job title vocabulary."""
    campaign = Campaign(id=CampaignId(new_id()), name=scenario["name"])
    storage.campaigns.add(campaign)
    storage.commit()

    agg = _build_aggregator(scenario)
    svc = DiscoveryService(storage, agg, embedding, LearningService(storage, embedding))
    crit = SearchCriteria(campaign_id=campaign.id, **scenario["criteria"])
    kept = svc.run_discovery(campaign.id, crit)

    expected_location = scenario["criteria"]["locations"][0]
    # The FULL criteria title must appear in every kept posting's title (case-
    # insensitive) — the same substring containment `_matches` enforces. A
    # last-token-only check would let e.g. "QA Engineer" satisfy a "Software
    # Engineer" scenario.
    expected_title = scenario["criteria"]["titles"][0].lower()
    assert kept, f"{scenario['name']}: expected at least one posting from the ok sources"
    for posting in kept:
        assert posting.location == expected_location
        assert expected_title in posting.title.lower()
        assert posting.source_key in scenario["expect_status"]


@pytest.mark.unit
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s["name"] for s in _SCENARIOS])
def test_region_category_scenario_records_per_source_outcomes(scenario, storage, embedding):
    """H2: every queried source's outcome (ok/empty/error) is recorded correctly for
    THIS scenario's region/category, and a failing/empty source never blocks or hides
    the outcome of any other source in the same run."""
    campaign = Campaign(id=CampaignId(new_id()), name=scenario["name"])
    storage.campaigns.add(campaign)
    storage.commit()

    agg = _build_aggregator(scenario)
    svc = DiscoveryService(storage, agg, embedding)
    crit = SearchCriteria(campaign_id=campaign.id, **scenario["criteria"])
    svc.run_discovery(campaign.id, crit)

    outcomes_by_key = {o["source_key"]: o for o in agg.last_source_outcomes}
    assert set(outcomes_by_key) == set(scenario["expect_status"])
    for key, expected_status in scenario["expect_status"].items():
        assert outcomes_by_key[key]["status"] == expected_status, (
            f"{scenario['name']}/{key}: expected {expected_status}, "
            f"got {outcomes_by_key[key]}"
        )
        if expected_status == SOURCE_ERROR:
            assert outcomes_by_key[key]["error"]  # never a bare unexplained failure


@pytest.mark.unit
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s["name"] for s in _SCENARIOS])
def test_region_category_scenario_shortfalls_are_honest_and_persisted(scenario, storage, embedding):
    """The shortfall vocabulary (core.rules.underdelivery) names exactly the
    underdelivering sources for THIS scenario, with plain-language messages, and the
    outcome round-trips through DiscoveryService persistence into
    ``discovery_sources.yield_stats.last_run`` — the same field the Settings > Job
    searches UI reads (``applicantCampaignSettings.js`` `_lastRunNote`) — so a source's
    degrade in one region/category run is not lost by the time the UI asks for it."""
    campaign = Campaign(id=CampaignId(new_id()), name=scenario["name"])
    storage.campaigns.add(campaign)
    storage.commit()

    agg = _build_aggregator(scenario)
    svc = DiscoveryService(storage, agg, embedding)
    crit = SearchCriteria(campaign_id=campaign.id, **scenario["criteria"])
    svc.run_discovery(campaign.id, crit)

    shortfalls = discovery_shortfalls(agg.last_source_outcomes)
    shortfall_keys = {s["source_key"] for s in shortfalls}
    expected_shortfall_keys = {
        k for k, status in scenario["expect_status"].items() if status != SOURCE_OK
    }
    assert shortfall_keys == expected_shortfall_keys
    for s in shortfalls:
        assert s["message"]  # every shortfall carries a ready-made plain-language line
        assert source_label(s["source_key"])  # label resolves without raising

    # Persistence round-trip: what the DiscoveryService wrote is what the sources
    # router would serialize verbatim (source_key, enabled, yield_stats, live) —
    # see ``app/routers/discovery_sources.py::list_sources``.
    persisted = {s.source_key: s for s in svc.list_sources(campaign.id)}
    for key, expected_status in scenario["expect_status"].items():
        last_run = persisted[key].yield_stats.get("last_run")
        assert last_run is not None, f"{scenario['name']}/{key}: no last_run persisted"
        assert last_run["status"] == expected_status


@pytest.mark.unit
def test_a_failed_board_never_crashes_or_hides_other_boards_same_run(storage, embedding):
    """Cross-cutting reliability property (not region/category-specific): a board that
    raises mid-run must never abort the whole discovery call, and its failure must be
    reported (not swallowed) alongside the sources that succeeded or were empty."""
    scenario = _SCENARIOS[0]
    campaign = Campaign(id=CampaignId(new_id()), name="mixed-outcome-run")
    storage.campaigns.add(campaign)
    storage.commit()

    agg = _build_aggregator(scenario)
    svc = DiscoveryService(storage, agg, embedding)
    crit = SearchCriteria(campaign_id=campaign.id, **scenario["criteria"])
    kept = svc.run_discovery(campaign.id, crit)  # must not raise

    assert kept  # the ok sources still yielded despite glassdoor's simulated block
    statuses = {o["source_key"]: o["status"] for o in agg.last_source_outcomes}
    assert statuses["jobspy:glassdoor"] == SOURCE_ERROR
    assert statuses["jobspy:indeed"] == SOURCE_OK
