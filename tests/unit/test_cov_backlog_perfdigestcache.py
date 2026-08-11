"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md's
exhaustive2/03_performance.md lens item #6, UPDATED for the 2026-08-10
DRAFT-UNBLOCK fix (commit 005c41a57, ``digest_service.py`` ``_build_scored_pairs``):

Original finding: "Engine digest GET re-scores every posting in the campaign,
unbounded, per request" — ``build_digest`` looped ``postings.list_for_campaign``
(no LIMIT) and called ``score_fn(posting, criteria)`` (``score_for_digest`` /
``score_posting``, both LLM-backed) per row on EVERY ``GET /api/digest/{id}``,
which the Portal loads on every open.

That was fixed TWICE, in two stages:

1. ``DigestCache`` (this file, unchanged) caches the scored ``(posting,
   row-without-warnings)`` pairs per (campaign, UTC day, posting count,
   criteria) so repeated GETs within the same window are a dict lookup.

2. DRAFT-UNBLOCK (2026-08-10, commit 005c41a57): even WITH the cache, a
   cache-miss rebuild still called ``score_for_digest`` per posting, which
   itself LLM-rescored whenever a posting's ``criteria_sig``/``learning_sig``
   drifted from its persisted value. With a large unscored/drifted backlog
   (thousands of postings) this made the digest GET — and the scheduler's
   auto-draft tick, which calls ``build_digest`` — take 40s+ and starved
   auto-draft entirely (ZERO applications ever drafted despite viable rows
   sitting there). ``_build_scored_pairs`` now NEVER calls ``score_for_digest``/
   ``score_posting``/any LLM-backed scorer: it reads the posting's PERSISTED
   ``viability_score``/``rationale`` directly (only ``ScoringService.is_viable``,
   a pure in-memory threshold comparison, is called) and SKIPS a posting with no
   persisted score entirely (except a user-added one, always kept). The
   background per-tick scoring pass (bounded, ``agent_loop.py``
   ``SCORING_BATCH_PER_TICK``) is the ONLY place that still calls the LLM to
   score a posting; the digest is a pure READ of whatever it already knows.

This file now asserts the STRONGER, current guarantee: ``build_digest`` never
calls the LLM-backed scorer AT ALL, for any posting, cache hit or miss,
first call or hundredth call (the exact "N LLM calls == 0" behavior the P0
root-cause fix + this file's task brief calls for). Row-cache hit/miss (the
original perf win) is now verified via a call-counting wrapper around
``postings.list_for_campaign`` instead of the (now-always-zero) scoring call
count, since the row cache still avoids re-scanning + re-building rows
(freshness bonus, keyword coverage, sort) even though nothing left to
re-score.

Safety-critical: the presubmit-safety warnings (duplicate-application /
scam-job) are EXCLUDED from the cached payload and recomputed fresh on every
call, cache hit or not — ``check_duplicate_application`` reads the campaign's
OTHER applications, which can flip a posting from "not a duplicate" to
"duplicate" intraday as the autonomous loop submits approved roles. The bulk
of this file proves that never goes stale.
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
    """A posting with a PERSISTED viability score by default (FR-DIG-4) — the
    digest hot path (post DRAFT-UNBLOCK) only surfaces postings that already
    carry one (or are user-added); an unscored posting is silently excluded,
    not scored on the fly."""
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
        viability_score=0.9,
        rationale={"text": "Strong match on skills and seniority."},
    )
    defaults.update(overrides)
    posting = JobPosting(**defaults)
    storage.postings.add(posting)
    storage.commit()
    return posting


class _CountingScoring:
    """Wraps a real ScoringService and counts LLM-backed rescoring calls.

    A real ``ScoringService`` (not a bare double) so ``is_viable``/persistence
    behave exactly as the production path; only the call count is instrumented.
    Post-DRAFT-UNBLOCK, ``build_digest`` must NEVER call ``score_for_digest``/
    ``score_posting`` — this file's whole point is proving that count stays 0.
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


class _CountingPostingsRepo:
    """Wraps a postings repo and counts ``list_for_campaign`` calls (proves a
    row-cache hit skips the campaign-wide posting scan, now that the scoring
    call count is always zero and can no longer serve as that proxy).

    ``DigestService.build_digest`` itself ALWAYS calls ``list_for_campaign``
    once directly (to hoist the campaign-wide posting/application reads out of
    the per-row presubmit-warnings loop — see its PERF 2026-08-10 comment),
    REGARDLESS of the row cache. ``_scored_pairs`` calls it a SECOND time only
    on a cache MISS (inside ``_build_scored_pairs``). So one ``build_digest``
    call costs 2 scans on a miss, but only 1 more (the always-on direct read)
    on a HIT — the constants below name that contract so each assertion below
    reads as "hit" or "miss/invalidate" rather than a bare magic number.
    """

    #: Extra ``list_for_campaign`` calls a single ``build_digest`` call costs
    #: when the row cache HITS (just ``build_digest``'s own direct read).
    HIT_DELTA = 1
    #: Extra calls when the row cache MISSES / is invalidated (the direct read
    #: PLUS ``_build_scored_pairs`` rebuilding the scored rows).
    MISS_DELTA = 2

    def __init__(self, inner) -> None:
        self._inner = inner
        self.list_calls = 0

    def list_for_campaign(self, cid):
        self.list_calls += 1
        return self._inner.list_for_campaign(cid)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _wire(*, shared_cache: DigestCache | None = None):
    storage = InMemoryStorage()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    scoring = _CountingScoring(storage)
    digest = DigestService(storage, notifier, scoring, digest_cache=shared_cache)
    return storage, digest, scoring


def _counting_postings(storage) -> _CountingPostingsRepo:
    counter = _CountingPostingsRepo(storage.postings)
    storage.postings = counter
    return counter


# ── P0 root cause: build_digest NEVER LLM-rescores (DRAFT-UNBLOCK) ────────────


def test_build_digest_never_calls_the_llm_backed_scorer():
    """The exact regression that stalled auto-draft for hours (2026-08-10 P0):
    ``build_digest`` must make ZERO LLM-backed scoring calls, for ANY posting,
    cache hit or cache miss, first call or a later call — it only reads each
    posting's PERSISTED viability_score/rationale."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    for i in range(5):
        _posting(
            storage, cid, id=JobPostingId(new_id()),
            title=f"Engineer {i}", source_url=f"https://acme.test/job/{i}",
            viability_score=0.7 + i * 0.01,
        )

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 5, "all 5 already-scored postings must surface"
    assert scoring.calls == 0, (
        "build_digest must NEVER call the LLM-backed scorer — it reads the "
        "persisted score directly (this is the P0 fix: the old behavior "
        "LLM-rescored every posting on a cache miss and starved auto-draft)"
    )

    # A second call (still a cache miss on a fresh DigestCache-less path, or a
    # hit with one) must ALSO make zero calls — there is no code path left in
    # ``_build_scored_pairs`` that reaches the scorer for an already-scored row.
    rows_2 = digest.build_digest(cid)
    assert len(rows_2) == 5
    assert scoring.calls == 0


def test_unscored_posting_is_excluded_not_scored_on_the_fly():
    """A posting with NO persisted viability_score (never reached by the
    background scoring pass yet) is silently excluded from the digest — the
    digest hot path must NEVER pay an LLM call to score it inline (that inline
    call, multiplied across a large unscored backlog, is exactly what used to
    time out the digest GET and starve the scheduler's auto-draft tick)."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid, viability_score=None, rationale={})

    rows = digest.build_digest(cid)
    assert rows == [], "an unscored posting must be excluded, not scored inline"
    assert scoring.calls == 0


def test_user_added_unscored_posting_is_kept_and_still_not_scored():
    """FR-DIG: a posting the user captured directly (paste-a-URL / bookmarklet)
    is NEVER silently dropped even with no score yet — but it is still not
    LLM-scored inline; it is shown with an honest 'scoring pending' rationale
    via the neutral 0.0 no-scoring-branch shape."""
    from applicant.core.entities.job_posting import USER_ADDED_SOURCE_KEY

    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(
        storage, cid, viability_score=None, rationale={}, source_key=USER_ADDED_SOURCE_KEY,
    )

    rows = digest.build_digest(cid)
    assert len(rows) == 1
    assert rows[0]["added_by_you"] is True
    assert scoring.calls == 0


# ── perf: repeated calls within the cache window skip the posting rescan ──────


def test_repeated_build_digest_calls_hit_the_row_cache():
    """Two GETs for the same campaign, same day, same posting count: the
    second call must be served from cache — ``postings.list_for_campaign`` is
    invoked exactly once (not once per call)."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    for i in range(5):
        _posting(
            storage, cid, id=JobPostingId(new_id()),
            title=f"Engineer {i}", source_url=f"https://acme.test/job/{i}",
        )
    counter = _counting_postings(storage)

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 5
    calls_after_first = counter.list_calls
    assert calls_after_first == counter.MISS_DELTA, "first call is a cache miss"

    rows_2 = digest.build_digest(cid)
    assert len(rows_2) == 5
    assert counter.list_calls == calls_after_first + counter.HIT_DELTA, (
        "a second call within the same day/posting-count/criteria window must be "
        "a cache HIT — it must cost only build_digest's own direct scan, not a "
        "second _build_scored_pairs rebuild"
    )
    assert {r["posting_id"] for r in rows_1} == {r["posting_id"] for r in rows_2}
    assert scoring.calls == 0


def test_build_digest_payload_also_benefits_from_the_row_cache():
    """The HTTP-facing ``build_digest_payload`` (what ``GET /api/digest/{id}``
    actually returns) rides the same cache — not just the lower-level
    ``build_digest``."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    counter = _counting_postings(storage)

    digest.build_digest_payload(cid)
    calls_after_first = counter.list_calls
    assert calls_after_first == counter.MISS_DELTA

    digest.build_digest_payload(cid)
    assert counter.list_calls == calls_after_first + counter.HIT_DELTA
    assert scoring.calls == 0


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
    counter = _counting_postings(storage)

    scoring_a = _CountingScoring(storage)
    digest_a = DigestService(storage, notifier, scoring_a, digest_cache=shared)
    digest_a.build_digest(cid)
    assert counter.list_calls == counter.MISS_DELTA
    assert scoring_a.calls == 0

    # A brand-new DigestService instance (new per-request rebuild), same storage,
    # same shared cache -- must be a cache HIT (only the direct scan, no rebuild).
    scoring_b = _CountingScoring(storage)
    digest_b = DigestService(storage, notifier, scoring_b, digest_cache=shared)
    digest_b.build_digest(cid)
    assert counter.list_calls == counter.MISS_DELTA + counter.HIT_DELTA, (
        "a fresh DigestService instance sharing the process-lived DigestCache "
        "must still be served from cache, or per-request rebuilds would defeat "
        "the cache entirely in production"
    )
    assert scoring_b.calls == 0


# ── invalidation: new posting / day rollover ───────────────────────────────────


def test_cache_invalidates_when_a_new_posting_is_added():
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    counter = _counting_postings(storage)

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 1
    calls_after_first = counter.list_calls

    # A new posting lands (the scheduler's discovery tick, mid-day) -- the
    # campaign's posting COUNT changes, which must invalidate the cache entry.
    _posting(storage, cid, id=JobPostingId(new_id()), title="Staff Engineer")

    rows_2 = digest.build_digest(cid)
    assert len(rows_2) == 2, "the new posting must appear on the very next GET"
    assert counter.list_calls == calls_after_first + counter.MISS_DELTA, (
        "the cache must have rebuilt (rescanned) rather than serving the stale "
        "1-row list"
    )
    assert scoring.calls == 0


def test_cache_invalidates_on_day_rollover():
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    counter = _counting_postings(storage)

    digest.build_digest(cid)
    calls_after_first = counter.list_calls
    assert calls_after_first == counter.MISS_DELTA

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

    assert counter.list_calls == calls_after_first + counter.MISS_DELTA, (
        "a day rollover must invalidate the cache and force a rebuild, not "
        "silently serve yesterday's digest forever"
    )
    assert scoring.calls == 0


def test_cache_invalidates_when_criteria_change():
    """A mid-day criteria edit must not be masked by the cache for the rest of
    the day -- same campaign/posting-count/day, different criteria."""
    from applicant.core.entities.search_criteria import SearchCriteria

    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    _posting(storage, cid)
    counter = _counting_postings(storage)

    crit_a = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    digest.build_digest(cid, crit_a)
    calls_after_first = counter.list_calls
    assert calls_after_first == counter.MISS_DELTA

    crit_b = SearchCriteria(campaign_id=cid, titles=("staff engineer",), keywords=("rust",))
    digest.build_digest(cid, crit_b)
    assert counter.list_calls == calls_after_first + counter.MISS_DELTA
    assert scoring.calls == 0


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
    # No cache available -> every call rebuilds (correct, just not cached) --
    # but still never LLM-scores.
    assert scoring.calls == 0


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
    counter = _counting_postings(storage)

    rows_1 = digest.build_digest(cid)
    assert len(rows_1) == 2
    row_1 = next(r for r in rows_1 if r["posting_id"] == new_posting.id)
    assert row_1["warnings"] == [], "no duplicate application exists yet"
    calls_after_first = counter.list_calls

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
    # Proves this was in fact a row-cache HIT: only build_digest's own direct
    # scan, no _build_scored_pairs rebuild.
    assert counter.list_calls == calls_after_first + counter.HIT_DELTA, (
        "this must have been a cache hit on the scored rows -- the warning "
        "freshness guarantee is only meaningful if the expensive part was cached"
    )
    row_2 = next(r for r in rows_2 if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "duplicate_cooldown" for w in row_2["warnings"]), (
        "a duplicate-application warning that became true AFTER the row cache "
        "was populated must still surface on the next call -- warnings must "
        "never be served stale"
    )
    assert scoring.calls == 0


def test_scam_warning_also_recomputed_fresh_on_a_cache_hit():
    """Companion to the duplicate-warning test: a placeholder-company scam signal
    must also survive a row-cache hit unchanged (it is static per-posting data,
    so this pins that the merge-in-fresh-warnings step runs on every call, not
    just that it happens to produce the right answer for the mutable case)."""
    storage, digest, scoring = _wire()
    cid = _campaign(storage)
    posting = _posting(storage, cid, company="Confidential")
    counter = _counting_postings(storage)

    rows_1 = digest.build_digest(cid)
    assert rows_1[0]["warnings"], "expected a scam/ghost warning for a placeholder company"

    calls_after_first = counter.list_calls
    rows_2 = digest.build_digest(cid)
    assert counter.list_calls == calls_after_first + counter.HIT_DELTA, (
        "second call must be a cache hit"
    )
    assert rows_2[0]["warnings"] == rows_1[0]["warnings"]
    assert rows_2[0]["posting_id"] == posting.id
    assert scoring.calls == 0


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
    assert scoring_b.calls == 0
    row_2 = next(r for r in rows_2 if r["posting_id"] == new_posting.id)
    assert any(w["check"] == "duplicate_cooldown" for w in row_2["warnings"]), (
        "the fresh per-request DigestService instance must still surface the "
        "duplicate warning even though the row payload came from the shared cache"
    )
