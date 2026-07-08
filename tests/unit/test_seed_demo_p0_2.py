"""Hermetic coverage for the P0-2 seeded-demo additions (issue #646).

Extends the audit §6 quick-win #49 seed with the surfaces the P0-2 story
requires to be non-empty: an activity/audit trail (~15 action events), a short
run history (momentum + streak), a SECOND library document (a cover letter), a
``DEMO_MODE`` gate, idempotent re-seeding, a residue-free clear, and a hard
"no secret/API key ever lands in seed data" invariant.

Everything here runs against ``InMemoryStorage`` (no DB), so it passes under an
unreachable ``DATABASE_URL`` — the hermetic in-memory lane. The Postgres lane
uses the SAME ``persist`` / ``purge`` code paths through the real repositories.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services import dev_seed as seed
from applicant.core.entities.action_event import ActionEvent
from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.generated_document import DocumentType
from applicant.core.ids import CampaignId
from applicant.core.state_machine import ApplicationState

# ── activity feed: ~15 action-trail entries ─────────────────────────────────


def test_build_demo_action_events_populate_the_activity_feed():
    postings = seed.build_demo_postings()
    variant = seed.build_demo_resume_variant()
    apps = seed.build_demo_applications(postings, variant)
    events = seed.build_demo_action_events(apps)

    # The story asks for ~15 activity-feed entries.
    assert 14 <= len(events) <= 16
    app_ids = {a.id for a in apps}
    for e in events:
        assert isinstance(e, ActionEvent)
        assert e.campaign_id == CampaignId(seed.DEMO_CAMPAIGN_ID)
        assert e.action and e.reason  # every row carries the "what" + the "why"
        # Every application-scoped row references a REAL seeded application (FK).
        if e.application_id is not None:
            assert e.application_id in app_ids
    # Ids are unique so a re-seed upserts rather than piling up.
    assert len({str(e.id) for e in events}) == len(events)
    # A realistic spread of action kinds (not 15 identical rows).
    assert len({e.action for e in events}) >= 5
    # Includes the headline lifecycle actions the demo narrates.
    actions = {e.action for e in events}
    assert {"discovered", "submitted", "interview_invited"} <= actions


# ── run history: momentum + streak ──────────────────────────────────────────


def test_build_demo_agent_runs_span_recent_consecutive_days():
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    runs = seed.build_demo_agent_runs(now=now)
    assert len(runs) >= 3
    for r in runs:
        assert isinstance(r, AgentRun)
        assert r.campaign_id == CampaignId(seed.DEMO_CAMPAIGN_ID)
        assert r.intent_sentence
        assert r.stats  # stats back the momentum recap totals

    # Distinct calendar days, consecutive, ending on "today" — so the supportive
    # streak (which counts back from today) renders instead of reading as broken.
    day_keys = sorted({r.timestamp.date() for r in runs})
    assert now.date() in day_keys
    for earlier, later in zip(day_keys, day_keys[1:], strict=False):
        assert (later - earlier) == timedelta(days=1)
    # At least one run records a submission (feeds the momentum funnel).
    assert any(int(r.stats.get("submitted", 0)) > 0 for r in runs)


# ── two library documents ───────────────────────────────────────────────────


def test_bundle_seeds_two_distinct_library_documents():
    bundle = seed.build_demo_bundle()
    assert bundle.cover_letter is not None
    assert bundle.material.type == DocumentType.RESUME
    assert bundle.cover_letter.type == DocumentType.COVER_LETTER
    # Distinct ids so both show in the library (not one overwriting the other).
    assert str(bundle.material.id) != str(bundle.cover_letter.id)
    # Both hang off the same (material-review) application, consistently.
    assert bundle.cover_letter.application_id == bundle.material.application_id


# ── persist through the REAL repositories (in-memory lane) ──────────────────


def _seed_into(storage: InMemoryStorage) -> dict:
    return seed.persist(storage, seed.build_demo_bundle())


def test_persist_writes_activity_runs_and_two_documents():
    storage = InMemoryStorage()
    counts = _seed_into(storage)

    assert counts["materials"] == 2
    assert counts["agent_runs"] >= 3
    assert 14 <= counts["action_events"] <= 16

    cid = CampaignId(seed.DEMO_CAMPAIGN_ID)
    assert len(storage.action_events.list_for_campaign(cid)) == counts["action_events"]
    assert len(storage.agent_runs.list_for_campaign(cid)) == counts["agent_runs"]
    assert len(storage.documents.list_for_campaign(cid)) == 2
    # Five+ applications spanning the trust-core stages are visible.
    apps = storage.applications.list_for_campaign(cid)
    assert len(apps) >= 5
    stages = {a.status for a in apps}
    assert {
        ApplicationState.DIGESTED,
        ApplicationState.MATERIAL_REVIEW,
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.AWAITING_RESPONSE,
    } <= stages


def test_reseed_is_idempotent_no_duplicate_rows():
    storage = InMemoryStorage()
    first = _seed_into(storage)
    cid = CampaignId(seed.DEMO_CAMPAIGN_ID)

    before = {
        "postings": len(storage.postings.list_for_campaign(cid)),
        "applications": len(storage.applications.list_for_campaign(cid)),
        "documents": len(storage.documents.list_for_campaign(cid)),
        "action_events": len(storage.action_events.list_for_campaign(cid)),
        "agent_runs": len(storage.agent_runs.list_for_campaign(cid)),
        "pending_actions": len(storage.pending_actions.list_open(cid)),
    }

    second = _seed_into(storage)  # re-seed
    after = {
        "postings": len(storage.postings.list_for_campaign(cid)),
        "applications": len(storage.applications.list_for_campaign(cid)),
        "documents": len(storage.documents.list_for_campaign(cid)),
        "action_events": len(storage.action_events.list_for_campaign(cid)),
        "agent_runs": len(storage.agent_runs.list_for_campaign(cid)),
        "pending_actions": len(storage.pending_actions.list_open(cid)),
    }
    assert before == after, "a re-seed must UPSERT, never duplicate rows"
    assert first == second


def test_clear_demo_data_leaves_no_residue():
    storage = InMemoryStorage()
    _seed_into(storage)
    cid = CampaignId(seed.DEMO_CAMPAIGN_ID)

    # Sanity: rows exist before the clear.
    assert storage.action_events.list_for_campaign(cid)
    assert storage.agent_runs.list_for_campaign(cid)

    seed.purge(storage, seed.DEMO_CAMPAIGN_ID)

    # Every seeded store — including the NEW activity/run stores — is empty.
    assert storage.campaigns.get(cid) is None
    assert storage.postings.list_for_campaign(cid) == []
    assert storage.applications.list_for_campaign(cid) == []
    assert storage.documents.list_for_campaign(cid) == []
    assert storage.action_events.list_for_campaign(cid) == []
    assert storage.agent_runs.list_for_campaign(cid) == []
    assert storage.pending_actions.list_open(cid) == []


# ── no secret / API key ever lands in seed data (ties to P1-0) ──────────────

_SECRET_KEY_HINT = re.compile(r"(api[_-]?key|secret|token|password|passwd|bearer)", re.I)
_SECRET_VALUE_PREFIX = ("sk-", "sk_", "ghp_", "gho_", "xoxb-", "Bearer ", "AKIA")


def _walk_strings(obj):
    """Yield ``(key_path, value)`` for every string reachable in the bundle."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _walk_kv(f.name, getattr(obj, f.name))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_kv(str(k), v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_strings(item)


def _walk_kv(key, value):
    if isinstance(value, str):
        yield key, value
    else:
        yield from _walk_strings(value)


def test_no_secret_or_api_key_is_written_into_seed_data():
    bundle = seed.build_demo_bundle()
    for key, value in _walk_strings(bundle):
        # A field NAMED like a secret must never carry a value in seed data.
        if _SECRET_KEY_HINT.search(key):
            assert value == "", f"seed field {key!r} carries a value: {value!r}"
        # And no value anywhere may look like a real credential.
        assert not value.startswith(_SECRET_VALUE_PREFIX), (
            f"seed field {key!r} looks like a credential: {value!r}"
        )


def test_demo_llm_tier_carries_no_api_key():
    """The gate-opener installs a LOCAL placeholder tier — never a real key."""
    assert seed._DEMO_LLM.get("api_key", "") == ""
