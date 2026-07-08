"""H2 — no silent underdelivery (road-to-market Phase 1.5 honesty invariants).

When the engine did LESS than asked, the shortfall is stated at the item level:

* a discovery source that returned nothing / failed / was rate-limit-skipped is
  reported per source (adapter outcome -> persisted ``yield_stats.last_run`` ->
  digest ``source_shortfalls`` + the digest email's shortfall lines);
* a pre-fill that left fields blank, failed fills, or deferred screening
  questions attaches a ``shortfall`` record to the ``final_approval`` pending
  action so "Materials approved" can never read as "everything filled".

These pin the whole chain the front-door renders (applicantDigest.js strip,
applicantToday/applicantPortal final-approval line, campaign-settings source
notes), so a regression here is a regression of a user-visible honesty claim.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySearxngDiscovery,
    JobSpySource,
    PerBoardRateLimiter,
    SampleSource,
)
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, DiscoverySourceId, new_id
from applicant.core.rules.underdelivery import (
    SOURCE_EMPTY,
    SOURCE_ERROR,
    SOURCE_OK,
    SOURCE_RATE_LIMITED,
    discovery_shortfalls,
    prefill_shortfall,
    source_label,
    source_shortfall_message,
)


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


# --- the pure vocabulary (core rule) ---------------------------------------


@pytest.mark.unit
class TestUnderdeliveryRule:
    def test_full_delivery_has_no_shortfall(self):
        # The absence of a statement must mean genuinely full delivery —
        # never a swallowed degrade.
        assert (
            prefill_shortfall(fields_detected=5, fields_filled=5) is None
        )
        assert prefill_shortfall(fields_detected=0, fields_filled=0) is None

    def test_failed_and_deferred_fields_are_named_item_level(self):
        s = prefill_shortfall(
            fields_detected=10,
            fields_filled=7,
            failed_fields=[{"selector": "#phone", "label": "Phone"}],
            deferred_questions=[{"selector": "#q", "label": "Why us?"}],
        )
        assert s is not None
        assert s["fields_unfilled"] == 3
        assert s["failed_fields"] == ["Phone"]
        assert s["deferred_questions"] == ["Why us?"]
        # The ready-made summary states counts AND names the items.
        assert "7 of the 10 fields" in s["summary"]
        assert "Phone" in s["summary"] and "Why us?" in s["summary"]
        # 3 unfilled = 1 failed + 1 deferred + 1 skipped/blank.
        assert "1 left blank" in s["summary"]

    def test_blank_only_shortfall_still_speaks(self):
        s = prefill_shortfall(fields_detected=4, fields_filled=2)
        assert s is not None
        assert "2 of the 4 fields" in s["summary"]
        assert "2 left blank" in s["summary"]

    def test_source_messages_per_status(self):
        assert "returned nothing" in source_shortfall_message("jobspy:indeed", SOURCE_EMPTY)
        assert "could not be searched" in source_shortfall_message(
            "jobspy:indeed", SOURCE_ERROR, error="boom"
        )
        assert "boom" in source_shortfall_message("jobspy:indeed", SOURCE_ERROR, error="boom")
        assert "skipped" in source_shortfall_message("jobspy:indeed", SOURCE_RATE_LIMITED)
        # Delivering sources make no statement — and never a fabricated one.
        assert source_shortfall_message("jobspy:indeed", SOURCE_OK) is None

    def test_source_labels_are_plain_language(self):
        assert source_label("jobspy:indeed") == "Indeed"
        assert source_label("searxng") == "Web search"
        assert source_label("rss:hn-hiring") == "Hn-hiring feed"

    def test_discovery_shortfalls_filters_ok(self):
        out = discovery_shortfalls(
            [
                {"source_key": "a", "status": SOURCE_OK, "found": 3},
                {"source_key": "b", "status": SOURCE_EMPTY, "found": 0},
                {"source_key": "c", "status": SOURCE_ERROR, "found": 0, "error": "x"},
            ]
        )
        assert [s["source_key"] for s in out] == ["b", "c"]
        assert all(s["message"] for s in out)


# --- adapter: per-source outcomes ------------------------------------------


class _BoomClient:
    def scrape(self, **kwargs):  # noqa: ARG002
        raise RuntimeError("board unreachable")


@pytest.mark.unit
class TestAggregatorOutcomes:
    def test_ok_empty_and_error_outcomes_are_recorded(self):
        cid = CampaignId(new_id())
        disc = JobSpySearxngDiscovery(
            sources=[
                SampleSource(key="full"),  # yields postings
                SampleSource(key="hollow", postings=[]),  # yields nothing
                JobSpySource(site="indeed", client=_BoomClient()),  # raises inside
            ]
        )
        disc.search(cid, SearchCriteria(campaign_id=cid))
        by_key = {o["source_key"]: o for o in disc.last_source_outcomes}
        assert by_key["full"]["status"] == SOURCE_OK and by_key["full"]["found"] > 0
        assert by_key["hollow"]["status"] == SOURCE_EMPTY
        assert by_key["jobspy:indeed"]["status"] == SOURCE_ERROR
        assert "board unreachable" in by_key["jobspy:indeed"]["error"]

    def test_rate_limited_skip_is_an_outcome_not_a_vanishing(self):
        cid = CampaignId(new_id())
        disc = JobSpySearxngDiscovery(
            sources=[SampleSource(key="full")],
            rate_limiter=PerBoardRateLimiter(max_calls=1, period_seconds=3600),
        )
        disc.search(cid, SearchCriteria(campaign_id=cid))  # consumes the one call
        disc.search(cid, SearchCriteria(campaign_id=cid))  # skipped this time
        assert disc.last_source_outcomes == [
            {
                "source_key": "full",
                "status": SOURCE_RATE_LIMITED,
                "found": 0,
                "error": None,
            }
        ]

    def test_outcomes_reset_per_call(self):
        # A stale prior run must never masquerade as the current one's outcome.
        cid = CampaignId(new_id())
        disc = JobSpySearxngDiscovery(sources=[SampleSource(key="full")])
        disc.search(cid, SearchCriteria(campaign_id=cid))
        first = disc.last_source_outcomes
        disc.search(cid, SearchCriteria(campaign_id=cid))
        assert disc.last_source_outcomes is not first


# --- service: outcomes persisted per source (yield_stats.last_run) ----------


@pytest.mark.unit
class TestDiscoveryServicePersistsOutcomes:
    def test_last_run_outcome_lands_on_the_registry_row(self, storage, campaign):
        disc = JobSpySearxngDiscovery(
            sources=[SampleSource(key="full"), SampleSource(key="hollow", postings=[])]
        )
        svc = DiscoveryService(storage, disc, LocalEmbedding())
        svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
        full = storage.discovery_sources.get(campaign.id, "full")
        hollow = storage.discovery_sources.get(campaign.id, "hollow")
        assert full.yield_stats["last_run"]["status"] == SOURCE_OK
        assert full.yield_stats["last_run"]["found"] > 0
        assert full.yield_stats["last_run"]["at"]
        assert hollow.yield_stats["last_run"]["status"] == SOURCE_EMPTY
        assert hollow.yield_stats["last_run"]["found"] == 0

    def test_adapter_without_outcomes_stays_signature_stable(self, storage, campaign):
        class _Legacy:
            """A minimal discovery double with no outcome reporting."""

            def available_sources(self):
                return ["legacy"]

            def is_source_enabled(self, key):  # noqa: ARG002
                return True

            def apply_toggles(self, toggles):  # noqa: ARG002
                return None

            def search(self, campaign_id, criteria, **kwargs):  # noqa: ARG002
                return []

        svc = DiscoveryService(storage, _Legacy(), LocalEmbedding())
        svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
        rec = storage.discovery_sources.get(campaign.id, "legacy")
        assert "last_run" not in (rec.yield_stats or {})


# --- digest: item-level statements on every digest ---------------------------


def _seed_source(storage, campaign_id, key, *, enabled=True, last_run=None):
    stats = {"last_run": last_run} if last_run is not None else {}
    storage.discovery_sources.upsert(
        DiscoverySource(
            id=DiscoverySourceId(new_id()),
            campaign_id=campaign_id,
            source_key=key,
            enabled=enabled,
            yield_stats=stats,
        )
    )
    storage.commit()


@pytest.mark.unit
class TestDigestSourceShortfalls:
    def test_payload_states_shortfalls_even_with_rows(self, storage, campaign):
        _seed_source(
            storage, campaign.id, "jobspy:indeed",
            last_run={"status": SOURCE_EMPTY, "found": 0, "at": "2026-07-08T00:00:00+00:00"},
        )
        _seed_source(
            storage, campaign.id, "searxng",
            last_run={"status": SOURCE_ERROR, "found": 0, "error": "timeout",
                      "at": "2026-07-08T00:00:00+00:00"},
        )
        _seed_source(
            storage, campaign.id, "jobspy:linkedin",
            last_run={"status": SOURCE_OK, "found": 4, "at": "2026-07-08T00:00:00+00:00"},
        )
        digest = DigestService(storage, notification=None)
        payload = digest.build_digest_payload(campaign.id)
        keys = [s["source_key"] for s in payload["source_shortfalls"]]
        assert keys == ["jobspy:indeed", "searxng"]
        messages = " ".join(s["message"] for s in payload["source_shortfalls"])
        assert "Indeed returned nothing" in messages
        assert "Web search could not be searched" in messages

    def test_disabled_sources_make_no_statement(self, storage, campaign):
        # Turning a source off is the user's own choice — not an underdelivery.
        _seed_source(
            storage, campaign.id, "jobspy:indeed", enabled=False,
            last_run={"status": SOURCE_EMPTY, "found": 0, "at": "2026-07-08T00:00:00+00:00"},
        )
        digest = DigestService(storage, notification=None)
        assert digest.build_digest_payload(campaign.id)["source_shortfalls"] == []

    def test_no_recorded_run_means_no_claim(self, storage, campaign):
        # A source that has never run gets NO statement either way — the digest
        # omits what it cannot verify rather than fabricating an outcome.
        _seed_source(storage, campaign.id, "jobspy:indeed")
        digest = DigestService(storage, notification=None)
        assert digest.build_digest_payload(campaign.id)["source_shortfalls"] == []

    def test_email_carries_the_shortfall_lines(self, storage, campaign):
        _seed_source(
            storage, campaign.id, "jobspy:indeed",
            last_run={"status": SOURCE_EMPTY, "found": 0, "at": "2026-07-08T00:00:00+00:00"},
        )
        digest = DigestService(storage, notification=None)
        email = digest.render_email(campaign.id)
        assert "Where I came up short on the last check" in email["html"]
        assert "Indeed returned nothing" in email["html"]

    def test_email_without_shortfalls_stays_clean(self, storage, campaign):
        digest = DigestService(storage, notification=None)
        email = digest.render_email(campaign.id)
        assert "came up short" not in email["html"]


# --- pre-fill: the final-approval item states its own shortfall --------------


@pytest.mark.unit
class TestFinalApprovalShortfall:
    def test_final_approval_payload_states_the_shortfall(self):
        # The standard fake Workday flow defers one essay question — even the
        # happy path must SAY so on the final-approval item instead of reading
        # as "all filled, just submit".
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from test_prefill_service import _app, _full_answers, _resume_full, _service

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        result = _resume_full(_service(storage), _app(cid), _full_answers(cid))
        final = [
            p for p in storage.pending_actions.list_open(cid) if p.kind == "final_approval"
        ]
        assert final, "run reached final approval"
        shortfall = final[0].payload.get("shortfall")
        assert shortfall is not None
        assert shortfall["fields_detected"] == result.fields_detected
        assert shortfall["fields_filled"] == result.fields_filled
        assert shortfall["deferred_questions"] == ["Why do you want to work here?"]
        assert "double-check the form" in shortfall["summary"]

    def test_failed_fill_is_named_on_the_final_approval_item(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from test_prefill_service import _app, _full_answers, _resume_full

        from applicant.adapters.browser.patchright_browser import PatchrightBrowser
        from applicant.adapters.detection.detection_monitor import DetectionMonitor
        from applicant.adapters.sandbox.local_sandbox import LocalSandbox
        from applicant.application.services.prefill_service import PrefillService

        class _FlakyBrowser:
            def __init__(self):
                self._inner = PatchrightBrowser()

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def fill_field(self, aid, selector, value):
                if selector == "#first-name":
                    raise RuntimeError("element detached")
                return self._inner.fill_field(aid, selector, value)

        cid = CampaignId(new_id())
        storage = InMemoryStorage()
        service = PrefillService(
            storage=storage,
            browser=_FlakyBrowser(),
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
        )
        _resume_full(service, _app(cid), _full_answers(cid))
        final = [
            p for p in storage.pending_actions.list_open(cid) if p.kind == "final_approval"
        ]
        assert final
        shortfall = final[0].payload.get("shortfall")
        assert shortfall is not None
        assert "First Name" in shortfall["failed_fields"]
        assert "failed to fill" in shortfall["summary"]
