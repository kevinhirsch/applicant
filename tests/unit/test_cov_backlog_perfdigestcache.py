"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md's
exhaustive2/03_performance.md lens item #6:

"Engine digest GET re-scores every posting in the campaign, unbounded, per
request" — ``build_digest`` looped ``postings.list_for_campaign`` (no LIMIT) and
called ``score_fn(posting, criteria)`` per row on EVERY ``GET /api/digest/{id}``,
which the Portal loads on every open. Even when ``ScoringService.score_for_digest``
reuses a persisted score, it still recomputes ``_learning_sig`` per posting (a real
``learning_model`` storage load) on every single row, every single call.

The fix: ``DigestCache`` (digest_service.py) caches the scored
``(posting, row-without-warnings)`` pairs per (campaign, UTC day, posting count,
criteria) so repeated GETs within the same day/posting-count/criteria window are a
dict lookup, not a rescore. It is deliberately process-lived (built once in
container.py, threaded through every ``DigestService`` construction site) because
the service itself is rebuilt every request/tick (CONC-REQ-1) — an instance
attribute would reset every call, same failure mode CLAUDE.md documents for
``ResumeLedger``/``DigestLedger``.

Safety-critical: the presubmit-safety warnings (duplicate-application / scam-job)
are EXCLUDED from the cached payload and recomputed fresh on every call, cache hit
or not — ``check_duplicate_application`` reads the campaign's OTHER applications,
which can flip a posting from "not a duplicate" to "duplicate" intraday as the
autonomous loop submits approved roles. The bulk of this file proves that never
goes stale.

Each assertion below was verified failing by hand against the pre-fix tree
(``git stash`` the digest_service.py / repositories.py / in_memory.py /
container.py changes, rerun, see a real failure — either an ``AttributeError`` on
``DigestCache``/``count_for_campaign`` not existing, or the call-count assertions
failing because every call rescored — then ``git stash pop`` to restore) before
this file was landed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import applicant.application.services.digest_service as digest_service_module
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestCache, DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    return cid


def _posting(storage, cid, **overrides) -> JobPosting:
    defaults = dict(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Backend Engineer",
        company="Acme Corp",
        source_url="https://acme.test/job",
        work_mode="remote",
        description=(
            "We need a senior backend engineer with 5+ years of experience in "
            "distributed systems, Python, and Go. Responsibilities include owning "
            "the payments service and mentoring junior engineers."
        ),
    )
    defaults.update(overrides)
    posting = JobPosting(**defaults)
    storage.postings.add(posting)
    storage.commit()
    return posting


class _CountingScoring:
    """Wraps a real ScoringService and counts ``score_for_digest`` calls.

    A real ``ScoringService`` (not a bare double) so ``is_viable``/persistence
    behave exactly as the production path; only the call count is instrumented.
    """

    def __init__(self, storage) -> None:
        self._inner = ScoringService(
            storage, llm=None, embedding=LocalEmbedding(), threshold=0
        )
        self.calls = 0

    def score_for_digest(self, posting, criteria=None):
        self.calls += 1
        return self._inner.score_for_digest(posting, criteria)

    def score_posting(self, posting, criteria=None):
        self.calls += 1
        return self._inner.score_posting(posting, criteria)

    def is_viable(self, scoring) -> bool:
        return self._inner.is_viable(scoring)


def _wire(*, shared_cache: DigestCache | None = None):
    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    scoring = _CountingScoring(storage)
    digest = DigestService(storage, notifier, scoring, digest_cache=shared_cache)
    return storage, digest, scoring


# ── perf: repeated calls within the cache window don't rescore ────────────────


def test_repeated_build_digest_calls_do_not_rescore_every_posting():
    """Two GETs for the same campaign, same day, same posting count: the second
    call must be served from cache — the scoring function is called exactly once
    PER POSTING (not once per posting per call)."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    for i in range(5):
        _posting(
            storage, cid, id=JobPostingId(new_id()),
            title=f"Engineer {i}", source_url=f"https://acme.test/job/{i}",
        )

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 5
    calls_after_first = scoring.calls
    assert calls_after_first == 5, "first call must score every posting"

    rows_2 = digest.build_digest(cid)
    assert len(rows_2) == 5
    assert scoring.calls == calls_after_first, (
        "a second call within the same day/posting-count/criteria window must be "
        "a cache hit — the scoring function must NOT be called again"
    )
    # Same row content served back (posting_id/score survive the cache round-trip).
    assert {r["posting_id"] for r in rows_1} == {r["posting_id"] for r in rows_2}


def test_build_digest_payload_also_benefits_from_the_row_cache():
    """The HTTP-facing ``build_digest_payload`` (what ``GET /api/digest/{id}``
    actually returns) rides the same cache — not just the lower-level
    ``build_digest``."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)

    digest.build_digest_payload(cid)
    calls_after_first = scoring.calls
    assert calls_after_first == 1

    digest.build_digest_payload(cid)
    assert scoring.calls == calls_after_first


def test_cache_is_shared_across_digestservice_rebuilds_not_just_within_one_instance():
    """Production rebuilds a FRESH ``DigestService`` every request/tick
    (CONC-REQ-1) — an instance-attribute cache would reset every call. Passing
    the SAME process-lived ``DigestCache`` into two SEPARATE ``DigestService``
    instances (mirroring container.py's wiring) must still hit on the second
    instance's first call."""
    shared = DigestCache()
    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    cid = _campaign(storage)
    _posting(storage, cid)

    scoring_a = _CountingScoring(storage)
    digest_a = DigestService(storage, notifier, scoring_a, digest_cache=shared)
    digest_a.build_digest(cid)
    assert scoring_a.calls == 1

    # A brand-new DigestService instance (new per-request rebuild), same storage,
    # same shared cache -- must NOT rescore.
    scoring_b = _CountingScoring(storage)
    digest_b = DigestService(storage, notifier, scoring_b, digest_cache=shared)
    digest_b.build_digest(cid)
    assert scoring_b.calls == 0, (
        "a fresh DigestService instance sharing the process-lived DigestCache "
        "must still be served from cache, or per-request rebuilds would defeat "
        "the cache entirely in production"
    )


# ── invalidation: new posting / day rollover ───────────────────────────────────


def test_cache_invalidates_when_a_new_posting_is_added():
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 1
    calls_after_first = scoring.calls

    # A new posting lands (the scheduler's discovery tick, mid-day) -- the
    # campaign's posting COUNT changes, which must invalidate the cache entry.
    _posting(storage, cid, id=JobPostingId(new_id()), title="Staff Engineer")

    rows_2 = digest.build_digest(cid)
    assert len(rows_2) == 2, "the new posting must appear on the very next GET"
    assert scoring.calls > calls_after_first, (
        "the cache must have rebuilt (rescored) rather than serving the stale "
        "1-row list"
    )


def test_cache_invalidates_on_day_rollover():
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)

    digest.build_digest(cid)
    calls_after_first = scoring.calls
    assert calls_after_first == 1

    # Same posting count, same criteria -- normally a cache hit. Advance "now" by
    # a day to simulate the UTC day rolling over between two GETs.
    real_datetime = digest_service_module.datetime

    class _TomorrowDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(days=1)

    digest_service_module.datetime = _TomorrowDatetime
    try:
        digest.build_digest(cid)
    finally:
        digest_service_module.datetime = real_datetime

    assert scoring.calls > calls_after_first, (
        "a day rollover must invalidate the cache and force a rescore, not "
        "silently serve yesterday's digest forever"
    )


def test_cache_invalidates_when_criteria_change():
    """A mid-day criteria edit must not be masked by the cache for the rest of
    the day -- same campaign/posting-count/day, different criteria."""
    from applicant.core.entities.search_criteria import SearchCriteria

    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)

    crit_a = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    digest.build_digest(cid, crit_a)
    calls_after_first = scoring.calls
    assert calls_after_first == 1

    crit_b = SearchCriteria(campaign_id=cid, titles=("staff engineer",), keywords=("rust",))
    digest.build_digest(cid, crit_b)
    assert scoring.calls > calls_after_first


def test_cache_falls_back_to_uncached_when_storage_lacks_count_for_campaign():
    """ROBUST: a storage double without ``count_for_campaign`` must degrade to
    the pre-cache always-fresh behavior, not raise."""

    class _NoCountPostingRepo:
        def __init__(self, inner):
            self._inner = inner

        def list_for_campaign(self, cid):
            return self._inner.list_for_campaign(cid)

    storage = InMemoryStorage()
    cid = _campaign(storage)
    _posting(storage, cid)
    storage.postings = _NoCountPostingRepo(storage.postings)  # strip count_for_campaign

    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    scoring = _CountingScoring(storage)
    digest = DigestService(storage, notifier, scoring, digest_cache=DigestCache())

    rows_1 = digest.build_digest(cid)
    rows_2 = digest.build_digest(cid)
    assert len(rows_1) == len(rows_2) == 1
    # No cache available -> every call rescores (correct, just not cached).
    assert scoring.calls == 2


# ── safety: presubmit warnings are NEVER served stale ──────────────────────────


def test_duplicate_warning_appears_on_the_very_next_call_despite_the_row_cache_hit():
    """The single most important test in this file.

    Two postings share (company, title). Neither has a duplicate warning on the
    first ``build_digest`` call (no submitted application yet against that pair).
    Without adding or removing ANY posting (the campaign's posting count is
    unchanged, so the row-cache entry is still valid), a THIRD-PARTY event lands:
    the OTHER posting's application is marked SUBMITTED_BY_USER. The very next
    ``build_digest`` call — a guaranteed row-cache HIT (same day, same count, same
    criteria) — must still surface the duplicate_cooldown warning. If warnings
    were cached alongside the rows, this would silently keep reporting "no
    warning" for the rest of the day, hiding a real duplicate-application risk.
    """
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    old_posting = _posting(storage, cid, title="Senior Backend Engineer", company="Acme Corp")
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Senior Backend Engineer",
        company="Acme Corp",
    )

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 2
    row_1 = next(r for r in rows_1 if r["posting_id"] == new_posting.id)
    assert row_1["warnings"] == [], "no duplicate application exists yet"
    calls_after_first = scoring.calls

    # A THIRD-PARTY event: the autonomous loop just submitted the OTHER posting's
    # application. Posting count is UNCHANGED (still 2) -- this is exactly the
    # row-cache HIT scenario.
    storage.applications.add(
        Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=old_posting.id,
            status=ApplicationState.SUBMITTED_BY_USER,
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    storage.commit()

    rows_2 = digest.build_digest(cid)
    # Proves this was in fact a row-cache HIT: no additional scoring calls.
    assert scoring.calls == calls_after_first, (
        "this must have been a cache hit on the scored rows -- the warning "
        "freshness guarantee is only meaningful if the expensive part was cached"
    )
    row_2 = next(r for r in rows_2 if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "duplicate_cooldown" for w in row_2["warnings"]), (
        "a duplicate-application warning that became true AFTER the row cache "
        "was populated must still surface on the next call -- warnings must "
        "never be served stale"
    )


def test_scam_warning_also_recomputed_fresh_on_a_cache_hit():
    """Companion to the duplicate-warning test: a placeholder-company scam signal
    must also survive a row-cache hit unchanged (it is static per-posting data,
    so this pins that the merge-in-fresh-warnings step runs on every call, not
    just that it happens to produce the right answer for the mutable case)."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    posting = _posting(storage, cid, company="Confidential")

    rows_1 = digest.build_digest(cid)
    assert rows_1[0]["warnings"], "expected a scam/ghost warning for a placeholder company"

    calls_after_first = scoring.calls
    rows_2 = digest.build_digest(cid)
    assert scoring.calls == calls_after_first, "second call must be a cache hit"
    assert rows_2[0]["warnings"] == rows_1[0]["warnings"]
    assert rows_2[0]["posting_id"] == posting.id


def test_warnings_never_cached_even_across_a_shared_process_lived_cache():
    """Mirrors the duplicate-warning test but through TWO SEPARATE DigestService
    instances sharing ONE process-lived DigestCache (the real production shape,
    CONC-REQ-1) -- proves the safety guarantee holds across the per-request
    rebuild, not just within one long-lived instance."""
    shared = DigestCache()
    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    cid = _campaign(storage)
    old_posting = _posting(storage, cid, title="Data Scientist", company="Globex")
    new_posting = _posting(
        storage, cid, id=JobPostingId(new_id()), title="Data Scientist", company="Globex",
    )

    scoring_a = _CountingScoring(storage)
    digest_a = DigestService(storage, notifier, scoring_a, digest_cache=shared)
    rows_1 = digest_a.build_digest(cid)
    row_1 = next(r for r in rows_1 if r["posting_id"] == new_posting.id)
    assert row_1["warnings"] == []

    storage.applications.add(
        Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=old_posting.id,
            status=ApplicationState.FINISHED_BY_ENGINE,
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    storage.commit()

    # A fresh DigestService (the next request's rebuild) sharing the SAME cache.
    scoring_b = _CountingScoring(storage)
    digest_b = DigestService(storage, notifier, scoring_b, digest_cache=shared)
    rows_2 = digest_b.build_digest(cid)
    assert scoring_b.calls == 0, "row cache hit across the per-request rebuild"
    row_2 = next(r for r in rows_2 if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "duplicate_cooldown" for w in row_2["warnings"]), (
        "the fresh per-request DigestService instance must still surface the "
        "duplicate warning even though the row payload came from the shared cache"
    )
